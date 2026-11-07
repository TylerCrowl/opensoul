"""OpenSoul Apple-clean web app — FastAPI + static frontend.

Serves plain-language 3-step UI; calls the same opensoul Python APIs.
Technical Comfy/SDK details stay under /api/health (Advanced).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from opensoul import __version__
from opensoul.character_pack import CharacterPack
from opensoul.comfy_client import sdk_status
from opensoul.models_registry import backend_choices, health_lines, stage_status
from opensoul.consistency import score_consistency
from opensoul.pipeline import build_character_pack, generate_stills, generate_talking_video
from opensoul.presets import build_shot_plan, caption_for, load_presets, shuffle_choice
from opensoul.script_parse import parse_script_markdown
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent / "web"
STATIC = WEB / "static"
DEMO = ROOT / "assets" / "demo_samples"
# Bundled demo characters (preview mode): Lumi first, Pixel second. Their packs in assets/ are never modified.
DEMO_NAME = "Lumi"
DEMO_PACK = DEMO / "lumi_pack"
DEMO_PACKS = {"Lumi": DEMO_PACK, "Pixel": DEMO / "pixel_pack"}
DEMO_SCENE = "Behind the coffee counter at night, holding a glass bottle of whole milk"
SCRIPTS = ROOT / "content" / "lumi"
DATA = Path(os.environ.get("OPENSOUL_DATA", ROOT / "data"))
LIBRARY = ROOT / "assets"  # saved characters: assets/<name>/character.json + their pictures

def _dev() -> bool:
    return os.environ.get("OPENSOUL_DEV", "") == "1"


# API docs (/docs, /redoc) load scripts and fonts from public CDNs, so they are off unless OPENSOUL_DEV=1.
app = FastAPI(title="OpenSoul", version=__version__, docs_url="/docs" if _dev() else None,
              redoc_url="/redoc" if _dev() else None, openapi_url="/openapi.json" if _dev() else None)

from app.local_guard import LocalOnlyMiddleware  # noqa: E402

app.add_middleware(LocalOnlyMiddleware)  # Host / Origin allow-list for every route (DNS rebinding, CSRF)

from starlette.exceptions import HTTPException as _StarletteHTTPException  # noqa: E402

NOT_FOUND_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Page not found · OpenSoul</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/static/theme.css" />
<style>body{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0}
main{max-width:28rem;padding:2rem;text-align:center}a{font-weight:600}</style></head>
<body><main><h1>This page isn't here</h1><p>OpenSoul doesn't have a page at this address.</p>
<p><a href="/">Back to OpenSoul</a></p></main></body></html>"""


@app.exception_handler(_StarletteHTTPException)
async def _http_error(request: Request, exc: _StarletteHTTPException):
    """P2-06: a browser that opens an unknown page gets a small HTML page, not raw JSON. The API keeps JSON."""
    from fastapi.exception_handlers import http_exception_handler
    from fastapi.responses import HTMLResponse

    if (exc.status_code == 404 and not request.url.path.startswith(("/api/", "/static/", "/assets/"))
            and "text/html" in request.headers.get("accept", "")):
        return HTMLResponse(NOT_FOUND_HTML, status_code=404)
    return await http_exception_handler(request, exc)


def _git(*args: str) -> str | None:
    """One read-only git query in the repo (None when git or the repo isn't there)."""
    import subprocess

    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _started() -> dict:
    """What this process loaded: the commit it started on and when. Compared with HEAD in build_info()."""
    from datetime import datetime, timezone

    return {"sha": _git("rev-parse", "HEAD"), "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}


_START = _started()


def build_info() -> dict:
    """Which code is running: the commit loaded at start, the repo's HEAD now, a dirty flag, start time, data dir.
    ``stale`` is true when HEAD moved after this server started (restart it with your usual start command)."""
    head = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain", "--untracked-files=no")
    loaded = _START["sha"]
    stale = bool(loaded and head and loaded != head)
    changed = _changed_since(loaded, head) if stale else []
    return {"sha": loaded, "short_sha": loaded[:7] if loaded else None, "head_sha": head,
            "head_short_sha": head[:7] if head else None, "stale": stale,
            "changed": changed[:20], "changed_count": len(changed),
            # unknown diff (e.g. rewritten history) counts as an app change; tests/docs-only commits don't
            "app_changed": stale and (not changed or any(f.startswith(APP_CODE) for f in changed)),
            "dirty": bool(status) if status is not None else None,
            "started": _START["started"], "pid": os.getpid(), "data_dir": tilde(DATA.resolve())}


def tilde(p) -> str:
    """A path for display: the home folder becomes '~', so no account name shows in status, logs or screenshots."""
    s, home = str(p), str(Path.home())
    return "~" + s[len(home):] if home and home != "/" and (s == home or s.startswith(home + os.sep)) else s


# Files whose change means the running app (server or pages) is out of date; tests/docs alone are not.
APP_CODE = ("app/", "opensoul/", "custom_nodes/", "presets/", "workflows/")


def _changed_since(loaded: str | None, head: str | None) -> list[str]:
    """Files changed between the commit this server loaded and HEAD ([] when unknown, e.g. history rewritten)."""
    out = _git("diff", "--name-only", f"{loaded}..{head}") if loaded and head else None
    return [x for x in (out or "").splitlines() if x.strip()]


def _include_storyboard() -> None:
    from app.storyboard_api import router as storyboard_router

    app.include_router(storyboard_router)


def _dry() -> bool:
    return os.environ.get("OPENSOUL_DRY_RUN", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "",
    }


def _scores_log() -> list[dict]:
    import json

    p = DEMO / "scores.json"
    if p.is_file():
        return json.loads(p.read_text()).get("demo_stills", [])
    return []


def _demo_stills(display: bool = True) -> list[str]:
    """The demo character's pre-baked stills, in scores.json order (one is off-model: the "Needs a redo" example).
    For display, an old (pre-rebuild) design shows as the character's card picture instead (pre_rebuild_hide)."""
    names = [r.get("file", "") for r in _scores_log()]
    from opensoul.demo_images import url

    return [(url(f"assets/demo_samples/{n}") if display else f"/assets/demo_samples/{n}")
            for n in names if n and (DEMO / n).is_file()]


def _sheet_url(display: bool = True) -> str | None:
    """The demo sheet picture; for display, an old (pre-rebuild) design shows as its card picture instead."""
    if (DEMO / "lumi_sheet_preview.jpg").is_file():
        if display:
            from opensoul.demo_images import url

            return url("assets/demo_samples/lumi_sheet_preview.jpg")  # an old design shows as its card picture
        return "/assets/demo_samples/lumi_sheet_preview.jpg"
    return None


def _old_design(p) -> str | None:
    """The cast name whose pre-rebuild design this picture shows (presets/demo_images.json pre_rebuild_hide)."""
    from opensoul.demo_images import pre_rebuild_name

    return pre_rebuild_name(p, DATA) if p else None


def _poster_url() -> str | None:
    """The demo's 9:16 preview picture: the audited still listed as tile_still in presets/demo_images.json.
    Never lumi_video_poster.png, a crop of a concept image (opensoul/export_guard.py)."""
    from opensoul.demo_images import load, url

    return url((load().get("tile_still") or {}).get("image"), kind="tile")


def _demo_name_of(pack_dir: str | Path | None) -> str | None:
    """Which bundled demo character a pack folder is (None for the user's own packs)."""
    if not pack_dir:
        return DEMO_NAME
    try:
        r = Path(pack_dir).resolve()
    except OSError:
        return None
    return next((n for n, d in DEMO_PACKS.items() if r == d.resolve()), None)


def _is_demo_pack(pack_dir: str | Path | None) -> bool:
    """True for a bundled demo character (empty pack_dir means the main demo, for API callers)."""
    return _demo_name_of(pack_dir) is not None


def _is_demo_name(name: str | None) -> bool:
    return _clean_name(name).lower() in {n.lower() for n in DEMO_PACKS}


def _demos() -> list[dict]:
    """The bundled demo characters for the Create page: Lumi (main), then Pixel."""
    out = []
    for n, d in DEMO_PACKS.items():
        if not (d / "pack.json").is_file():
            continue
        cp = CharacterPack.load(d)
        refs = [r for r in cp.ref_images if Path(r).is_file()]
        sheet = _sheet_url() if n == DEMO_NAME else (f"/assets/demo_samples/{d.name}/refs/{Path(refs[0]).name}" if refs else None)
        if n != DEMO_NAME and refs and _old_design(refs[0]):
            sheet = _file_url(Path(refs[0]))
        from opensoul.demo_images import cast_card

        out.append({"name": cp.name, "pack_dir": str(d), "prompt_lock": cp.prompt_lock, "sheet_url": sheet if _dry() else None,
                    **cast_card(cp.name)})  # card_url: the audited picture shown on its card (presets/demo_images.json)
    return out


def _clean_name(name: str | None) -> str:
    """Auto-correct the character name: trim, collapse spaces, never empty."""
    n = " ".join(str(name or "").split())[:60]
    return n or "My character"


def _pack_folder(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_" else "_" for c in _clean_name(name).replace(" ", "_"))
    return keep.strip("_") or "My_character"


def _name_card(name: str, dest: Path, size: tuple[int, int] = (720, 1280),
               subtitle: str = "Preview · no character sheet yet") -> Path:
    """Neutral stand-in image labelled with the character's name (dry-run only, never the demo character)."""
    from PIL import Image, ImageDraw, ImageFont

    w, h = size
    img = Image.new("RGB", size, "#ECECF0")
    d = ImageDraw.Draw(img)
    cx = w // 2
    d.ellipse((cx - w // 9, int(h * 0.30), cx + w // 9, int(h * 0.30) + 2 * (w // 9)), fill="#C7C7CF")
    d.rounded_rectangle((cx - w // 4, int(h * 0.48), cx + w // 4, int(h * 0.78)), radius=w // 8, fill="#C7C7CF")
    try:
        font = ImageFont.load_default(size=max(18, w // 14))
        small = ImageFont.load_default(size=max(12, w // 28))
    except TypeError:  # older Pillow
        font = small = ImageFont.load_default()
    d.text((cx, int(h * 0.86)), _clean_name(name), fill="#3A3A3C", font=font, anchor="mm")
    if subtitle:
        d.text((cx, int(h * 0.92)), subtitle, fill="#8E8E93", font=small, anchor="mm")
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)
    return dest


def _scripts() -> list[dict]:
    out = []
    if not SCRIPTS.is_dir():
        return out
    for p in sorted(SCRIPTS.glob("*.md")):
        if p.stem == "README":
            continue
        raw = p.read_text(encoding="utf-8")
        parsed = parse_script_markdown(raw, p.stem)
        out.append(
            {
                "id": p.stem,
                "title": parsed.title,
                "spoken": parsed.spoken,
                "tip": parsed.tip,
                "shots": parsed.shots,
            }
        )
    return out


def _first_run() -> dict:
    from opensoul import demo_images, first_run

    from opensoul import preview_samples

    d = first_run.load()
    if not d.get("items") and preview_samples.available():  # P0-01: real sample clips instead of a placeholder
        d = {**d, "mode": "samples", "title": preview_samples.load().get("title") or "Samples",
             "items": preview_samples.first_run_items()}
    d["still"] = demo_images.first_run_still()  # shown only while no example clip has passed
    return d


def _demo_card(name: str) -> str | None:
    from opensoul.demo_images import cast_card

    return cast_card(name)["card_url"]


@app.get("/api/bootstrap")
def bootstrap():
    """Initial dry-run state for the guided UI."""
    pack = None
    prompt = ""
    if (DEMO_PACK / "pack.json").is_file():
        cp = CharacterPack.load(DEMO_PACK)
        pack = str(DEMO_PACK)
        prompt = cp.prompt_lock
        name = cp.name
    else:
        name = DEMO_NAME
    from opensoul.demo_images import cast_card

    scripts = _scripts()
    from opensoul import zimage_master as _zm

    return {
        "version": __version__,
        "dry_run": _dry(),
        "master_batch": max(2, min(8, int(_zm.load_config().get("master_batch") or 4))),  # "Make N options"
        "demos": _demos(),  # Lumi (main demo), then Pixel
        "first_run": _first_run(),  # examples slot: audited film, else accepted re-render tiles, else preset clips
        # The page opens on a fresh, empty character; the demo is opt-in (button or ?demo=1).
        "new_character": {
            "name": "",
            "pack_dir": "",
            "prompt_lock": "",
            "sheet_url": None,
            "status": "New character. Type a name and a short description, then click Make character sheet.",
        },
        "character": {
            "name": name,
            "pack_dir": pack,
            "prompt_lock": prompt,
            "sheet_url": _sheet_url() if _dry() else None,
            "card_url": _demo_card(name),  # the audited picture for "Starring" (presets/demo_images.json)
            "card_placeholder": cast_card(name)["card_placeholder"],  # pre-rebuild: no new sheet from its pictures
            "status": "Demo character ready. You can edit the description or continue."
            if _dry()
            else "Upload a few photos to begin.",
        },
        "photos": {
            "items": [
                {
                    "url": u,
                    "score": (_scores_log()[i]["score"] if i < len(_scores_log()) else None),
                    "passed": (_scores_log()[i]["passed"] if i < len(_scores_log()) else True),
                    "label": ("Pass" if (_scores_log()[i]["passed"] if i < len(_scores_log()) else True) else "Needs a redo"),
                }
                for i, u in enumerate(_demo_stills())
            ]
            if _dry()
            else [],
            "scene": DEMO_SCENE,
        },
        "video": {
            "poster_url": _poster_url() if _dry() else None,
            "scripts": scripts,
            "note": "Preview poster. Connect a studio to render the full talking video."
            if _dry()
            else "",
        },
    }


class ShotRequest(BaseModel):
    name: str = ""
    camera: str | None = None
    effect: str | None = None
    era: str = "iphone_ugc"
    line: str = ""
    voice: str | None = None
    pack_dir: str = ""
    seed: int = 42
    advanced: dict | None = None
    tts_backend: str | None = None
    lipsync_backend: str | None = None


class ShareRequest(BaseModel):
    video_url: str = ""
    title: str = ""
    name: str = "My character"
    pack_dir: str = ""
    camera: str | None = None
    effect: str | None = None


def _ascii_slug(text: str, fallback: str, limit: int = 24) -> str:
    """ASCII-safe file name part: 'Lumi the Elf!' -> 'lumi_the_elf'."""
    import re
    import unicodedata

    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")[:limit].strip("_")
    return t or fallback


def _export_name(name: str, move: str | None, now=None) -> str:
    """Unique, readable export name so browsers don't save opensoul_vertical (1), (2)..."""
    from datetime import datetime

    stamp = (now or datetime.now()).strftime("%H%M%S")
    return f"opensoul_{_ascii_slug(name, 'character')}_{_ascii_slug(move or '', 'shot')}_{stamp}.mp4"


@app.get("/api/presets")
def presets():
    """Tile data for the Shot step. Thumbnails may not be rendered yet."""
    from opensoul.demo_images import clip_allowed, load as demo_images, tile_still

    data = load_presets()
    cfg = demo_images()
    still = tile_still(cfg)
    for kind in ("camera", "effects"):
        for it in data[kind]:
            rel = (it.get("thumbnail") or "").removeprefix("/")
            # Only review-passed clips (presets/demo_images.json); the rest show their glyph card.
            it["thumb_ready"] = bool(rel) and (ROOT / rel).is_file() and clip_allowed(it["id"], cfg)
            if rel and not it["thumb_ready"]:
                # e.g. a release archive leaves the tile clips out, or the clip hasn't passed: the glyph card shows
                # instead, and the clip's URL isn't sent at all (no capture can pick up an unpassed clip)
                it["thumbnail"] = None
            it["tile_still"] = None if it["thumb_ready"] else still
    from opensoul import camera_moves

    data["camera_rules"] = camera_moves.rules()  # stacked moves: the shot sheet greys out clashes with the same rules
    return data


@app.get("/api/voices")
def voices(name: str = ""):
    """Built-in Orpheus voices, the emotion tags the line editor offers, and this character's saved voice."""
    from opensoul import orpheus
    from opensoul.character_voices import voice_for

    from opensoul import voice_engine as VE

    avail = VE.available_voice_ids(DATA)  # OS-055: None = every voice works here (or the studio is not known)
    return {"voices": [{**v, "available": avail is None or v["id"] in avail} for v in orpheus.VOICES],
            "tags": list(orpheus.TAGS), "default": orpheus.DEFAULT_VOICE,
            "engines": VE.studio_engines(),  # OS-054: {engine: on the studio} in studio mode, else None
            "character_voice": voice_for(DATA, name) if name.strip() else None}


class VoiceSampleIn(BaseModel):
    voice: str


@app.post("/api/voices/sample")
def voice_sample(req: VoiceSampleIn):
    """OS-049: hear a voice before you give it to a character. A short fixed line, made once per voice and engine
    (a placeholder tone in Preview mode)."""
    from opensoul import lipsync as L
    from opensoul import orpheus
    from opensoul import voice_engine as VE

    try:
        voice = orpheus.check_voice(req.voice)
    except ValueError as e:
        raise HTTPException(400, str(e))
    engine = VE.default_for_new()
    if engine in VE.CLONING:  # a sample has no clip: the named-voice engine the studio has
        engine = VE.no_clip_fallback(VE.studio_engines())
    dest = DATA / "voice_samples" / f"{voice}_{engine}{'_dry' if _dry() else ''}.wav"
    if not dest.is_file():
        try:
            L.synth_line("Hello. This is how I sound in every shot.", voice, dest, dry_run=_dry(), engine=engine)
        except Exception as e:  # noqa: BLE001  studio down / no ffmpeg: a plain message
            raise HTTPException(503, f"Couldn't make the sample: {e}")
    return {"audio_url": _file_url(dest), "voice": voice, "voice_engine": engine, "placeholder": _dry()}


@app.get("/api/shuffle")
def shuffle(seed: int | None = None):
    return shuffle_choice(seed)


def _pack_prompt(pack_dir: str) -> str:
    d = Path(pack_dir) if pack_dir else DEMO_PACK
    if (d / "pack.json").is_file():
        return CharacterPack.load(d).prompt_lock
    return ""


def _shot_prompt(pack_dir: str, name: str = "") -> str:
    """Look lock for a shot: the pack's, else a saved character's. The demo's lock only for the demo character,
    never for someone else (an empty pack_dir with a new name used to get the demo character's description)."""
    if pack_dir and not _is_demo_pack(pack_dir):
        return _pack_prompt(pack_dir)
    if not name.strip() or _clean_name(name).lower() == DEMO_NAME.lower():
        return _pack_prompt("")
    lib = _library(name)
    return (lib or {}).get("prompt_lock", "")


def _check_backend(stage: str, choice: str | None) -> str | None:
    """Validate an Advanced-drawer backend pick against the model registry."""
    if not choice:
        return None
    choice = choice.strip().lower()
    row = next((c for c in backend_choices() if c["stage"] == stage), None)
    if row is None or choice not in row["all_ids"]:
        raise HTTPException(400, f"Unknown {stage} option {choice!r}. Pick one from Advanced.")
    ok = any(o["id"] == choice and o["available"] for o in row["options"])
    if not ok and not _dry():
        hint = f" Run {row['download_hint']} where your studio is set up." if row["download_hint"] else ""
        raise HTTPException(400, f"{row['label']} option {choice!r} isn't installed.{hint}")
    return choice


@app.get("/api/backends")
def backends():
    """Per-stage backend pickers for Advanced (installed options only; local file checks)."""
    return {"stages": backend_choices()}


def _in_app_tree(p: str | Path) -> bool:
    """A caller-supplied path that resolves inside the data folder or the repo. Nothing else."""
    try:
        return bool(str(p)) and _inside(Path(p), DATA, ROOT)
    except (OSError, ValueError):
        return False


@app.post("/api/shot")
def make_shot(req: ShotRequest):
    from opensoul.orpheus import TagError

    if req.pack_dir and not _is_demo_pack(req.pack_dir) and not _in_app_tree(req.pack_dir):
        raise HTTPException(400, "OpenSoul cannot find that character. Return to step 1.")
    tts_b = _check_backend("voice", req.tts_backend)
    ls_b = _check_backend("lipsync", req.lipsync_backend)
    voice, voice_from = req.voice, "shot" if req.voice else ""
    if not voice and req.line.strip():
        from opensoul.character_voices import voice_for_shot

        voice, voice_from = voice_for_shot(DATA, req.name, None)  # the character's own voice by default
    try:
        plan = build_shot_plan(
            camera=req.camera,
            effect=req.effect,
            era=req.era,
            line=req.line[:280],
            voice=voice,
            character_prompt=_shot_prompt(req.pack_dir, req.name),
            seed=req.seed,
            overrides=req.advanced,
            lipsync_backend=ls_b,
            tts_backend=tts_b,
            pack_dir=req.pack_dir or (str(DEMO_PACK) if _clean_name(req.name).lower() == DEMO_NAME.lower() else ""),  # their pronoun
        )
    except TagError as e:
        raise HTTPException(400, str(e))
    except KeyError as e:
        raise HTTPException(400, f"Unknown preset {e}. Pick a tile and try again.")
    except (ValueError, TypeError) as e:  # e.g. Advanced width "abc": a clear 400, not a 500
        raise HTTPException(400, f"Check the Advanced settings: {e}")
    import uuid

    from opensoul.shot import run_shot

    out = DATA / "outputs" / "shots" / uuid.uuid4().hex[:10]
    image = _shot_image(req.pack_dir, out, req.name)
    if image is None:
        raise HTTPException(
            400,
            "This character has no picture yet. Return to step 1. Click Make character sheet "
            "(a description is enough).",
        )
    try:
        res = run_shot(plan, image, out)
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    except Exception as e:  # ffmpeg/Comfy failures -> friendly message
        raise HTTPException(500, f"Couldn't render the shot: {e}")
    quick = None
    try:  # D1: a single shot is always a project. Recorded in "Quick shots" (files in place); never fails the shot.
        from opensoul import migrate

        r = migrate.record(DATA, out, name=_clean_name(req.name) if req.name.strip() else "", camera=req.camera or "static",
                           effect=req.effect, line=req.line[:280] if req.name.strip() else "", prompt=str(plan.get("prompt") or "")[:2000],
                           seed=req.seed, placeholder=_dry())
        quick = {"project": migrate.QUICK_ID, "shot": r[0], "take": r[1]} if r else None
    except Exception as e:  # noqa: BLE001
        print(f"[opensoul] quick shot not recorded in the project: {e}")
    return {
        "quick_shot": quick,
        "plan": plan,
        "dry_run": _dry(),
        # The demo poster is only ever shown for the demo character.
        "poster_url": _poster_url() if _dry() and _is_demo_pack(req.pack_dir) and (
            not req.name or _clean_name(req.name).lower() == DEMO_NAME.lower()) else None,
        "video_url": f"/api/file?path={_key(res.video)}",
        "voice": voice, "voice_from": voice_from,  # "character" (the default) or "shot" (picked for this shot)
        "steps": res.steps,
        "notes": res.notes,
        "note": "Preview render: connect a studio to render the real take." if _dry() else "",
    }


# ---------------------------------------------------------------- the current character's own pictures
_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def _md5(p: Path) -> str:
    import hashlib

    return hashlib.md5(p.read_bytes()).hexdigest()


_DEMO_HASHES: dict[str, str] | None = None


def _demo_hashes() -> dict[str, str]:
    """Fingerprints of every bundled demo picture -> whose it is (a demo pack's own folder, else the main demo),
    so a pack that borrowed a demo face under another name is caught."""
    global _DEMO_HASHES
    if _DEMO_HASHES is None:
        out: dict[str, str] = {}
        owners = {d.resolve(): n for n, d in DEMO_PACKS.items()}
        if DEMO.is_dir():
            for f in DEMO.rglob("*"):
                if f.suffix.lower() in _IMG_EXT and f.is_file():
                    owner = next((n for d, n in owners.items() if d in f.resolve().parents), DEMO_NAME)
                    out[_md5(f)] = owner
        _DEMO_HASHES = out
    return _DEMO_HASHES


def _demo_owner(p: Path) -> str | None:
    try:
        return _demo_hashes().get(_md5(p))
    except OSError:
        return None


def _is_demo_image(p: Path, name: str | None = None) -> bool:
    """A demo character's picture, unless it belongs to ``name`` itself (Lumi's own pack may hold Lumi's demo refs)."""
    owner = _demo_owner(p)
    return owner is not None and not (name and owner.lower() == _clean_name(name).lower())


def _own_refs(pack_dir: str | Path | None) -> list[Path]:
    """The pack's own reference images, minus anything that is really a demo-character picture."""
    if not pack_dir or _is_demo_pack(pack_dir):
        return []
    d = Path(pack_dir)
    if not (d / "pack.json").is_file():
        return []
    cp = CharacterPack.load(d)
    kept = []
    for raw in cp.ref_images:
        p = Path(raw)
        try:
            # A pack may name a picture outside itself. That file is not this character's reference.
            if p.is_file() and _inside(p, d) and not _is_demo_image(p, cp.name):
                kept.append(p)
        except (OSError, ValueError):
            continue
    return kept


def _library(name: str) -> dict | None:
    """A saved character under assets/<slug>/character.json (e.g. assets/lumi/), matched by name."""
    import json

    slug = _ascii_slug(name, "")
    if not slug:
        return None
    d = LIBRARY / slug
    cj = d / "character.json"
    if not cj.is_file():
        return None
    try:
        meta = json.loads(cj.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if _clean_name(meta.get("name", "")).lower() != _clean_name(name).lower():
        return None

    def pick(key: str) -> Path | None:
        f = (meta.get(key) or {}).get("file")
        p = d / f if f else None
        return p if p and p.is_file() and not _is_demo_image(p, meta.get("name")) else None

    return {"name": meta.get("name"), "prompt_lock": meta.get("prompt_lock", ""), "reference": pick("reference"),
            "sheet": pick("sheet"), "dir": d}


def _pack_borrows_demo(pack_dir: Path) -> bool:
    """A pack saved by an older build may hold demo-character pictures under another name."""
    if not (pack_dir / "pack.json").is_file():
        return False
    cp = CharacterPack.load(pack_dir)
    return any(Path(r).is_file() and _is_demo_image(Path(r), cp.name) for r in cp.ref_images)


def _pack_sheet(pack_dir: str | Path | None) -> Path | None:
    if not pack_dir or _is_demo_pack(pack_dir):
        return None
    for ext in (".jpg", ".png"):
        p = Path(pack_dir) / f"character_sheet{ext}"
        if p.is_file() and not _is_demo_image(p, CharacterPack.load(pack_dir).name if (Path(pack_dir) / "pack.json").is_file() else None):
            return p
    return None


def _character_look(name: str, pack_dir: str | Path | None, use_library: bool = True) -> dict:
    """Best pictures of the current character: its pack first, then its library folder. Never the demo."""
    refs = _own_refs(pack_dir)
    sheet = _pack_sheet(pack_dir)
    if refs or sheet:
        # A made sheet puts the six views after the anchor; prefer the full-body front view as the still.
        # (Preview-mode views are stamped placeholders, so preview keeps the real anchor picture.)
        front = None if _dry() else next((r for r in refs if r.name.startswith("sheet_full_front")), None)
        still = front or (refs[0] if refs else None)
        return {"still": still, "sheet": sheet, "source": "pack"}
    lib = _library(name) if use_library else None
    if lib and (lib["reference"] or lib["sheet"]):
        return {"still": lib["reference"], "sheet": lib["sheet"], "source": "library"}
    return {"still": None, "sheet": None, "source": None}


def _key(p) -> str:
    """The short, URL-safe name /api/file uses for a file (P1-04): 'data/<path in DATA>' or '<path in the repo>'.
    No absolute path (on a Mac it holds the account name) reaches a URL, a screenshot or a bug report."""
    from urllib.parse import quote

    q = Path(p).resolve()
    for prefix, root in (("data/", DATA), ("", ROOT)):
        r = root.resolve()
        if q == r or q.is_relative_to(r):
            rel = q.relative_to(r).as_posix()
            if not prefix and (rel == "data" or rel.startswith("data/")):
                rel = "./" + rel  # the repo's own data folder, when DATA is elsewhere: not the user's data
            return quote(prefix + rel, safe="/")
    return quote(str(p), safe="/")


def _from_key(raw: str) -> Path:
    """The file a /api/file key names (the reverse of _key). Absolute paths still work (old links)."""
    raw = str(raw or "")
    if Path(raw).is_absolute():
        return Path(raw).resolve()
    if raw == "data" or raw.startswith("data/"):
        return (DATA / raw[5:]).resolve()
    return (ROOT / raw).resolve()


def file_of_url(url: str) -> Path:
    """The file a '/api/file?path=…' URL points at (for tests and the share route)."""
    from urllib.parse import parse_qs, urlsplit

    return _from_key((parse_qs(urlsplit(str(url)).query).get("path") or [""])[0])


def _inside(p: Path, *roots: Path) -> bool:
    """Is ``p`` inside one of ``roots``? A real path check: '/repo_shots' is not inside '/repo'."""
    q = Path(p).resolve()
    return any(q == r.resolve() or q.is_relative_to(r.resolve()) for r in roots)


def _dot_path(p: Path, *roots: Path) -> bool:
    """A dot folder or dotfile below the root (.git, .venv, .env); the root itself may live under a dot folder."""
    q = Path(p).resolve()
    for r in roots:
        r = r.resolve()
        if q.is_relative_to(r):
            return any(part.startswith(".") for part in q.relative_to(r).parts)
    return False


def _file_url(p: Path | None) -> str | None:
    if p is None:
        return None
    import time as _t

    from opensoul.demo_images import cast_card, pre_rebuild_name

    old = pre_rebuild_name(p, DATA)
    if old:  # an old Lumi/Mio/Ren design: show their card picture instead (presets/demo_images.json pre_rebuild_hide)
        return cast_card(old)["card_url"]
    from opensoul.export_guard import blocked

    if blocked(p):  # a repo file derived from a closed-generator image (export_guard): never handed to the UI
        from opensoul.demo_images import PLACEHOLDERS, url

        return url(PLACEHOLDERS["scene"]) if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".svg"} else None

    return f"/api/file?path={_key(p)}&v={int(p.stat().st_mtime) if p.exists() else int(_t.time())}"


@app.get("/api/look")
def character_look(name: str = "", pack_dir: str = "", library: int = 1):
    """Pictures to show for the character on screen (sheet panel, tiles, previews)."""
    name = _clean_name(name) if name.strip() else ""
    if pack_dir and not (_is_demo_pack(pack_dir) or _inside(Path(pack_dir), DATA)):
        raise HTTPException(400, "Unknown character folder.")
    look = _character_look(name, pack_dir, bool(library)) if (name or pack_dir) else {"still": None, "sheet": None, "source": None}
    lib = _library(name) if name and library else None
    found = {"name": lib["name"], "prompt_lock": lib["prompt_lock"]} if lib else None
    if name and library and not pack_dir and lib is None:
        # A character saved in the app under this name (e.g. made from a description in the Storyboard, maybe with no
        # picture yet): Create finds it too, the same pack the cast uses (the original, not a newer <name>_N).
        from app.storyboard_api import _pack_cast, _resolve_pack, _variants

        packs = _pack_cast()
        own = _resolve_pack(name, packs)
        if own:
            look = {**_character_look(name, own["pack_dir"], False), "source": "library"}
            found = {"name": own["name"], "prompt_lock": own["prompt_lock"], "folder": own.get("folder"),
                     "fields": _saved_fields(own["pack_dir"]),
                     "variants": [v["folder"] for v in _variants(name, own["pack_dir"], packs)]}
    return {
        "still_url": _file_url(look["still"]),
        "sheet_url": _file_url(look["sheet"]),
        "source": look["source"],
        "library": found,
        # an old (pre-rebuild) design shows as its card picture: Create captions it as a placeholder
        "placeholder": bool(_old_design(look.get("sheet")) or _old_design(look.get("still"))),
    }


def _shot_image(pack_dir: str, work: Path | None = None, name: str = "") -> Path | None:
    """First usable image of the *current* character.

    The demo pack uses its poster frame. Any other character uses its own pictures (pack, then its
    library folder); with none, preview mode uses a neutral name card. Never the demo character."""
    if _is_demo_pack(pack_dir) and (not name or _clean_name(name).lower() == DEMO_NAME.lower()):
        return ROOT / _poster_url().removeprefix("/") if _poster_url() else None
    d = Path(pack_dir) if pack_dir and not _is_demo_pack(pack_dir) else None
    if not name and d is not None:
        name = CharacterPack.load(d).name if (d / "pack.json").is_file() else d.name.replace("_", " ")
    look = _character_look(name, d)
    if look["still"] is not None:
        return look["still"]
    if _dry():
        return _name_card(name or "My character", (work or DATA / "outputs" / "cards") / "name_card.png")
    return None


def _export_vertical(src: Path | None, dest: Path) -> bool:
    from opensoul import media

    if src is None or not src.is_file():
        return False
    try:
        media.to_vertical(src, dest)
        return True
    except media.MediaError:
        return False


@app.post("/api/share")
def share(req: ShareRequest):
    """Export a vertical 9:16 MP4 and a ready-to-paste caption."""
    caption = caption_for({"title": req.title}, req.name or "My character")
    src: Path | None = None
    if req.video_url.startswith("/api/file?path="):
        from urllib.parse import parse_qs, urlsplit

        # Storyboard take URLs carry a cache-buster (&v=<mtime>); read the path parameter only.
        cand = _from_key((parse_qs(urlsplit(req.video_url).query).get("path") or [""])[0])
        if _inside(cand, ROOT, DATA):
            src = cand
    elif req.video_url.startswith("/assets/"):  # a shipped take (e.g. the demo's approved Shot 1, presets/demo_images.json)
        from urllib.parse import unquote, urlsplit

        cand = (ROOT / unquote(urlsplit(req.video_url).path).lstrip("/")).resolve()
        if _inside(cand, ROOT / "assets") and cand.is_file():
            src = cand
    elif _poster_url() and _is_demo_pack(req.pack_dir) and _clean_name(req.name).lower() == DEMO_NAME.lower():
        src = ROOT / _poster_url().removeprefix("/")  # demo only: never put the demo face under another name
    from opensoul.export_guard import blocked

    kept_in_app = blocked(src)
    if kept_in_app:  # concept images, the demo film and anything cut from them never leave the app
        src = None
    out = DATA / "outputs" / "share"
    out.mkdir(parents=True, exist_ok=True)
    filename = _export_name(req.name or "My character", req.effect or req.camera or req.title)
    dest = out / filename
    ok = _export_vertical(src, dest)
    dry = _dry()
    return {
        "caption": caption,
        "mp4_url": f"/api/file?path={_key(dest)}" if ok else None,
        "filename": filename,
        # Preview mode exports the placeholder clip: allowed, but labelled honestly.
        "placeholder": dry,
        "note": "" if ok else ("This demo clip plays in the app but isn't exported. Make your own shot to share." if kept_in_app
                               else "Generate a shot first, then export." if src is None else "Video export needs ffmpeg or a rendered clip."),
    }


@app.get("/api/health")
def health():
    """Advanced / technical status — not shown on the main path."""
    sdk = sdk_status()
    reachable = _studio_reachable(sdk.get("COMFY_BASE_URL") or "")
    dry = _dry()
    stages = stage_status()
    summary = [
        {"label": "Mode", "value": "Preview mode: sample takes, no GPU" if dry else "Studio: real renders"},
        {"label": "Comfy SDK", "value": (f"Installed (v{sdk.get('version')})" if sdk.get("comfy_sdk_importable")
                                         else "Not installed")},
        {"label": "Studio", "value": "Connected" if reachable else "Not connected"},
        {"label": "OpenSoul version", "value": __version__},
    ]
    build = build_info()
    code = build["short_sha"] or "unknown"
    if build["stale"]:
        code += " · the code changed since this server started: restart it"
    elif build["dirty"]:
        code += " · with local edits"
    summary.append({"label": "Code", "value": code})
    if dry:  # P1-03: Preview mode needs no models; say so instead of a list of "missing" rows with terminal commands
        summary.extend({"label": x["label"], "value": "Needed only for a studio" if "missing" in x["value"] else x["value"]}
                       for x in health_lines())
    else:
        summary.extend(health_lines())
    return {
        "version": __version__,
        "dry_run": dry,
        "sdk": sdk,
        "studio_reachable": reachable,
        # Plain lines for the System status panel; the raw fields above stay for "details".
        "summary": summary,
        "stages": stages,
        "build": build,
    }


def _studio_reachable(url: str, timeout: float = 0.8) -> bool:
    """Is anything answering at COMFY_BASE_URL? Any HTTP reply counts; no request body is sent."""
    if not url.startswith(("http://", "https://")):
        return False
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen(url.rstrip("/") + "/", timeout=timeout)  # noqa: S310 - local status probe
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


@app.post("/api/character")
async def create_character(
    name: str = Form("My character"),
    prompt_lock: str = Form(""),
    seed: int = Form(42),
    use_library: bool = Form(True),
    look: str = Form(""),
    outfit: str = Form(""),
    images: list[UploadFile] = File(default=[]),
):
    """Create's Save: the same save as the cast (storyboard_api.save_character), writing the character's own folder.
    Create asks for the rights tick in the page before it sends a photo."""
    from app.storyboard_api import save_character

    out, _c = await save_character(name=name, description=prompt_lock, uploads=images, replace=True, seed=seed,
                                   use_library=use_library, require_consent=False)
    _record_fields(out, look, outfit)
    pack = CharacterPack.load(out)
    sheet_url = _file_url(Path(pack.ref_images[0])) if pack.ref_images else None
    return {
        "name": pack.name,
        "pack_dir": str(out),
        "prompt_lock": pack.prompt_lock,
        "sheet_url": sheet_url,
        "has_images": bool(pack.ref_images),
        "status": "Character saved. Next, choose a shot." if pack.ref_images else
                  "Character saved from your description. Next, choose a shot, or make a character sheet for a locked look.",
    }


@app.post("/api/cast")
async def cast_api(
    name: str = Form(""),
    description: str = Form(""),
    kind: str = Form("reference"),
    consent: bool = Form(False),
    images: list[UploadFile] = File(default=[]),
    image: UploadFile | None = File(default=None),
):
    """The one cast API: add a character (description, or up to three pictures with the rights tick, or a sheet).
    /api/storyboard/cast and /api/character are kept as aliases of the same save."""
    from app.storyboard_api import new_cast_member

    return await new_cast_member(name=name, description=description, kind=kind, consent=consent, image=image, images=images)


@app.get("/api/cast")
def cast_list():
    from app.storyboard_api import cast

    return cast()


# ---------------------------------------------------------------- Character Sheet (one tap)
_SHEET_JOBS: dict[str, dict] = {}


def _safe_path(raw: str) -> Path | None:
    """Accept a file path or an /api/file?path= URL, but only inside the repo or the data dir."""
    if raw.startswith("/api/file?path="):
        from urllib.parse import parse_qs, urlsplit

        raw = (parse_qs(urlsplit(raw).query).get("path") or [""])[0]
    elif raw.startswith("/assets/"):
        raw = str(ROOT / raw.removeprefix("/"))
    if not raw:
        return None
    p = _from_key(raw)
    if not _inside(p, ROOT, DATA) or not p.is_file():
        return None
    return p


def _pack_anchor(pack_dir: str, name: str = "") -> Path | None:
    if _is_demo_pack(pack_dir):
        d = DEMO_PACKS.get(_demo_name_of(pack_dir) or DEMO_NAME, DEMO_PACK)
        if (d / "pack.json").is_file():
            for r in CharacterPack.load(d).ref_images:
                if Path(r).is_file():
                    return Path(r)
        return None
    refs = _own_refs(pack_dir)
    if refs:
        return refs[0]
    lib = _library(name) if name else None
    return lib["reference"] if lib else None


def _sheet_view_json(job: dict) -> dict:
    views = job.get("views", [])
    done = sum(1 for v in views if v.get("status") == "done")
    return {
        "job_id": job["id"],
        "state": job["state"],
        "stage": job.get("stage", ""),
        "done": done,
        "total": len(views) or 6,
        "views": views,
        "flagged": [v["id"] for v in views if v.get("flagged")],
        "studio_flagged": [v["id"] for v in views if v.get("flag_source") == "studio"],
        "preview_note": PREVIEW_SHEET_LINE if job.get("dry_run") else "",
        "sheet_url": job.get("sheet_url"),
        "download_url": job.get("download_url"),
        "pack_dir": job.get("pack_dir"),
        "dry_run": job.get("dry_run"),
        "error": job.get("error", ""),
    }


@app.post("/api/sheet")
async def make_sheet(
    consent: bool = Form(False),
    name: str = Form("My character"),
    prompt_lock: str = Form(""),
    pack_dir: str = Form(""),
    image_path: str = Form(""),
    seed: int = Form(4242),
    use_library: bool = Form(True),
    master_id: str = Form(""),
    look: str = Form(""),
    outfit: str = Form(""),
    style: str = Form(""),
    image: UploadFile | None = File(default=None),
):
    """One tap: one reference image -> six-view sheet -> Soul Pack ready for shots.

    ``master_id`` (Describe): the master that is showing. The sheet is always built from that one: with no pack yet it
    is saved first (refs/ref_00); a pack whose ref_00 is a different picture is refused (409).

    Source: an uploaded photo, else ``image_path`` (a generated character still), else the current
    character's reference image. Runs in the background; poll GET /api/sheet/{job_id}."""
    import uuid

    from opensoul.character_sheet import load_preset, make_character_sheet

    name = _clean_name(name)
    has_upload = image is not None and bool(image.filename)
    # Consent is about photos: only an uploaded image needs it. A text-only character needs none.
    if has_upload and not consent:
        raise HTTPException(400, "Please confirm you own this picture or have permission to use it.")
    if pack_dir and _is_demo_pack(pack_dir) and name.lower() != DEMO_NAME.lower():
        pack_dir = ""  # renamed away from the demo: this is a new character, don't reuse the demo's face
    if master_id and not has_upload:
        mwork = DATA / "outputs" / "masters" / master_id
        if not _MASTER_ID.match(master_id) or not (mwork / "master.png").is_file() or not (mwork / "master.json").is_file():
            raise HTTPException(404, "That master isn't here any more. Generate it again.")
        # A stale master: the words were edited after it was drawn, so it no longer shows this Look.
        mf = (json.loads((mwork / "master.json").read_text(encoding="utf-8")).get("fields") or {})
        same = lambda x, y: " ".join((x or "").split()).lower() == " ".join((y or "").split()).lower()
        if (look.strip() and "look" in mf and not same(look, mf.get("look"))) or (
                outfit.strip() and "outfit" in mf and not same(outfit, mf.get("outfit"))):
            raise HTTPException(409, "Your description changed after OpenSoul made this master. Click 1 · Make 4 options (or Generate one) first.")
        if not pack_dir:
            pack_dir = save_master(master_id, name)["pack_dir"]
        anchor = Path(pack_dir) / "refs" / "ref_00.png"
        if not anchor.is_file() or _md5(anchor) != _md5(mwork / "master.png"):
            raise HTTPException(409, "The master that's showing isn't the one saved for this character. Click Make character sheet again.")
        image_path = ""
    job_id = uuid.uuid4().hex[:10]
    work = DATA / "outputs" / "sheets" / job_id
    work.mkdir(parents=True, exist_ok=True)
    ref: Path | None = None
    from_text = False
    if has_upload:
        data = await image.read()
        if not data:
            raise HTTPException(400, "That file is empty. Pick a photo and try again.")
        ref = work / f"reference{Path(image.filename).suffix.lower() or '.png'}"
        ref.write_bytes(data)
        try:
            from PIL import Image as _Image

            _Image.open(ref).verify()
        except Exception:
            raise HTTPException(400, "That file isn't an image we can read. Try a JPG or PNG.")
    elif image_path:
        ref = _safe_path(image_path)
        if ref is None:
            raise HTTPException(400, "Couldn't find that character picture. Pick it again.")
    elif pack_dir or (name.lower() == DEMO_NAME.lower() and not prompt_lock.strip()):
        ref = _pack_anchor(pack_dir, name)
    elif use_library and _library(name) and _library(name)["reference"]:
        ref = _library(name)["reference"]  # a saved character (assets/<name>/): start from its real reference
    if ref is None and not has_upload and not image_path and not pack_dir:
        # The user's own character by this name (e.g. made from a description in the Storyboard): extend that pack
        # with the sheet instead of starting a duplicate <name>_2 (the one the cast pickers show, newest first).
        from app.storyboard_api import _resolve_pack

        own = _resolve_pack(name)  # the original <name> pack, never a newer <name>_N that happens to share the name
        if own:
            pack_dir = own["pack_dir"]
            ref = _pack_anchor(pack_dir, name)
    if ref is None and not has_upload and not image_path:
        # Text only: draw a reference from the description first.
        prompt_lock = prompt_lock.strip() or (_pack_prompt(pack_dir) if pack_dir and not _is_demo_pack(pack_dir) else "")
        if len(prompt_lock) < 8:
            raise HTTPException(400, "Describe your character in a few words (look, hair, outfit), or add a photo.")
        from_text = True
    if ref is None and not from_text:
        raise HTTPException(400, "Add a photo or pick a character first.")
    if ref is not None and not has_upload and _old_design(ref):
        # A pre-rebuild placeholder (presets/demo_images.json pre_rebuild_hide): never the source of a new sheet.
        raise HTTPException(409, f"{name}'s picture is a placeholder until we rebuild them. Click 1 · Make 4 options (or Generate one) first.")
    # The sheet always lands in the user's own pack (the demo pack in assets/ is never modified).
    target = Path(pack_dir) if pack_dir else None
    if target is not None and not _is_demo_pack(target) and _pack_borrows_demo(target):
        target = None  # never extend a pack that holds demo pictures under another name
    if target is None or _is_demo_pack(target) or not _inside(target, DATA):
        target = DATA / "packs" / _pack_folder(name)
        if not has_upload and not image_path and not from_text and _is_demo_pack(pack_dir):
            prompt_lock = prompt_lock or _pack_prompt(pack_dir)
        if target.exists() and (has_upload or from_text or _pack_borrows_demo(target)):
            # A new photo (or a pack holding demo pictures) starts a fresh character in the next free folder
            # (<name>_2, _3, ...). An existing pack is never deleted, moved or overwritten here.
            target = _free_pack_folder(target)
    elif has_upload and (target / "pack.json").is_file():
        # A new photo for the character that's open (pack_dir sent): same rule, a fresh <name>_N pack; the open pack's
        # anchor and sheet views are never overwritten by a different photo.
        target = _free_pack_folder(DATA / "packs" / _pack_folder(name))
    preset = load_preset()
    from opensoul import looks as LK
    from opensoul import text_master as _tmx

    look_id = _tmx.look_of(look, style if style in _tmx.STYLES else "")
    preset = LK.sheet_preset(preset, look_id)  # OS-010: a drawn character keeps its drawn style in all six views
    job = {"id": job_id, "state": "running", "stage": "Queued", "dry_run": _dry(), "pack_dir": str(target),
           "fields": {"look": look, "outfit": outfit}, "look": look_id,
           "views": [{"id": v["id"], "label": v["label"], "status": "queued", "checks": [], "note": ""}
                     for v in preset["views"]]}
    _SHEET_JOBS[job_id] = job
    from opensoul.character_voices import ensure_voice

    from opensoul.voice_engine import available_voice_ids

    # a new character gets a voice nobody else uses, of the character's gender (OS-048), on the studio (OS-055)
    ensure_voice(DATA, name, text=prompt_lock, available=available_voice_ids(DATA))

    job["work"] = str(work)

    def run() -> None:
        nonlocal ref
        try:
            if from_text:
                job["stage"] = f"Drawing {name} from your description"
                ref = _reference_from_text(name, prompt_lock, work / "reference")
            from opensoul.character_sheet import wants_subtle_ears

            subtle = wants_subtle_ears(prompt_lock)  # e.g. "short subtle pointed elf ears": prompt, check and trim
            res = make_character_sheet(ref, work, consent=True, subject=prompt_lock, seed=seed, dry_run=_dry(),
                                       pack_dir=target, name=name, progress=_sheet_progress(job), preset=preset,
                                       checklist_overrides={"pointed_ears": True, "ear_style": "subtle"} if subtle else None,
                                       ear_trim=subtle)
            if from_text:
                from opensoul import text_master as _tm

                _record_text_origin(target, prompt_lock, int((preset.get("from_text") or {}).get("seed", 7)),
                                    _tm.fields(look, outfit) if (look or outfit) else None,
                                    master="refs/" + Path(ref).name if ref else "")
            _sheet_done(job, res)
        except Exception as e:  # friendly message, keep details for the status box
            job["state"], job["error"] = "error", f"Couldn't make the sheet: {e}"
            job["stage"] = job["error"]

    _start(run)
    return _sheet_view_json(job)


def _free_pack_folder(folder: Path) -> Path:
    """The first of <name>_2, <name>_3, ... next to ``folder`` that doesn't exist yet."""
    i = 2
    while (cand := folder.with_name(f"{folder.name}_{i}")).exists():
        i += 1
    return cand


def _reference_from_text(name: str, description: str, out: Path) -> Path:
    """Front reference portrait from a description alone (workflow 07t on the studio computer).

    Preview mode draws a neutral card labelled with the character's name instead."""
    if _dry():
        return _name_card(name, out / "reference.png", (832, 1248), "Preview · drawn from the description in Studio")
    from opensoul import character_sheet as cs

    make_ref = getattr(cs, "make_reference_from_text", None)
    if make_ref is None:
        raise RuntimeError("this install can't draw a character from text yet; add a photo instead")
    return Path(make_ref(description, out)[0])


def _record_fields(pack_dir, look: str, outfit: str) -> None:
    """pack.json meta.fields {look, outfit}: Look and Outfit kept apart so Create can fill them back in separately.
    A look made from words already keeps them in meta.origin.fields; older packs have neither (all of it is Look)."""
    look, outfit = " ".join(str(look or "").split()), " ".join(str(outfit or "").split())
    pj = Path(pack_dir) / "pack.json" if pack_dir else None
    if not (look or outfit) or pj is None or not pj.is_file() or not _inside(pj, DATA):
        return
    data = json.loads(pj.read_text(encoding="utf-8"))
    meta = data.setdefault("meta", {})
    if (meta.get("origin") or {}).get("fields"):
        return
    meta["fields"] = {"look": look, "outfit": outfit}
    pj.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _saved_fields(pack_dir) -> dict | None:
    """{look, outfit[, age, style]} saved for a pack, or None for an older pack (its whole description is the Look)."""
    try:
        meta = json.loads((Path(pack_dir) / "pack.json").read_text(encoding="utf-8")).get("meta") or {}
    except (OSError, TypeError, ValueError):
        return None
    f = (meta.get("origin") or {}).get("fields") or meta.get("fields")
    if not isinstance(f, dict) or not (f.get("look") or f.get("outfit")):
        return None
    return {k: str(f.get(k) or "") for k in ("look", "outfit", "age", "style")}


def _record_text_origin(pack_dir: Path, prompt: str, seed: int, fields: dict | None = None, master: str = "",
                        workflow: str = "", master_prompt: str = "", best_of: dict | None = None) -> None:
    """pack.json meta.origin for a look made from words only (opensoul/text_master.py)."""
    from opensoul import text_master as tm

    pj = Path(pack_dir) / "pack.json"
    if not pj.is_file():
        return
    data = json.loads(pj.read_text(encoding="utf-8"))
    refs = data.get("ref_images") or []
    rec = tm.origin_record(prompt, seed, fields or tm.fields(look=prompt), preview=_dry(),
                           master=master if master in refs else (refs[0] if refs else ""), workflow=workflow or tm.WORKFLOW)
    if master_prompt:
        rec["master_prompt"] = master_prompt  # the exact words the master model got (07z)
    if best_of:
        rec["best_of"] = best_of  # seeds drawn, every option kept (options/), and which one was picked
    data.setdefault("meta", {})["origin"] = rec
    pj.write_text(json.dumps(data, indent=2), encoding="utf-8")


_MASTER_ID = re.compile(r"^[0-9a-f]{10}$")


_MASTER_JOBS: dict[str, dict] = {}
_MASTER_TIMES: list[float] = []  # seconds of finished studio masters (this process), for the "about N s" estimate


def _master_json(job: dict) -> dict:
    out = {k: job.get(k) for k in ("master_id", "name", "prompt_lock", "prompt", "seed", "next_seed", "preview", "label",
                                    "state", "stage", "error", "backend", "model", "eta_s", "look_stripped")}
    out["url"] = job.get("url") if job.get("state") == "done" else None
    rec = job.get("best_of")
    if rec:  # "Make N options": one tile per seed, then the user picks one
        work = DATA / "outputs" / "masters" / job["master_id"]
        out["options"] = [{"seed": c["seed"], "state": c["state"],
                           "url": f"/api/file?path={_key(work / c['file'])}" if c["state"] == "done" else None} for c in rec["candidates"]]
        out["pick"] = (rec.get("pick") or {}).get("seed")
    out["done"] = job.get("state") in ("done", "error", "cancelled")
    return out


def _draw_one(job: dict, seed: int, dest: Path) -> Path:
    """One master picture for ``seed`` at ``dest``: a labelled card in preview mode, else 07z (or 07t)."""
    import time as _t

    from opensoul import zimage_master as zm

    if _dry():
        delay = float(os.environ.get("OPENSOUL_MASTER_PREVIEW_DELAY", "0" if os.environ.get("OPENSOUL_SHEET_SYNC") == "1" else "1.2"))
        t_end = _t.monotonic() + max(0.0, delay)
        while _t.monotonic() < t_end:
            if job.get("cancel"):
                raise zm.MasterCancelled(job["master_id"])
            _t.sleep(0.1)
        # an option tile shows its own legible caption in the app ("Option 2 · #34"), so its card carries no tiny text
        _name_card(job["name"], dest, (832, 1248), "" if job.get("best_of") else f"Preview master · variation {seed}")
    elif job["backend"] == "zimage":
        cfg = zm.load_config()

        def got_pid(pid: str) -> None:
            job["prompt_id"] = pid
            job["stage"] = "Drawing your master in your studio…"
        zm.run(job["prompt"], seed, dest, cfg=cfg, on_prompt_id=got_pid, should_cancel=lambda: bool(job.get("cancel")))
    else:
        from opensoul import character_sheet as cs

        got = cs.make_reference_from_text(job["prompt_lock"], dest.parent, seeds=[seed])
        if job.get("cancel"):
            raise zm.MasterCancelled(job["master_id"])
        shutil.copyfile(got[0], dest)
    return dest


def _write_master_json(job: dict, work: Path, seed: int) -> None:
    (work / "master.json").write_text(json.dumps({"name": job["name"], "prompt": job["prompt_lock"], "seed": seed,
                                                  "master_prompt": job.get("prompt", ""), "fields": job["fields"],
                                                  "preview": _dry(), "backend": job["backend"],
                                                  "workflow": job["workflow"]}, indent=2), encoding="utf-8")


def _draw_master(job: dict, dest: Path) -> None:
    """Runs in the background (or inline under OPENSOUL_SHEET_SYNC=1): queued -> running -> done | error | cancelled.
    With job["best_of"] ("Make N options") every seed is drawn in turn and kept; nothing is the master until picked."""
    import time as _t

    from opensoul import best_of as bo
    from opensoul import zimage_master as zm

    work = dest.parent
    t_start = _t.monotonic()
    try:
        job["state"], job["stage"] = "running", "Drawing your master…"
        rec = job.get("best_of")
        if rec:
            n = len(rec["candidates"])

            def render(seed: int, out: Path) -> Path:
                i = next(k for k, c in enumerate(rec["candidates"]) if c["seed"] == seed)
                job["stage"] = f"Drawing option {i + 1} of {n}…"
                try:
                    return _draw_one(job, seed, out)
                except zm.MasterCancelled:
                    raise bo.Cancelled(seed)
            bo.run(rec, work, render, should_cancel=lambda: bool(job.get("cancel")),
                   on_change=lambda r: bo.save(r, work / "best_of.json"))
            bo.save(rec, work / "best_of.json")
            got = bo.done(rec)
            if not got:
                errs = [c.get("error") for c in rec["candidates"] if c.get("error")]
                if errs:
                    raise RuntimeError(errs[0])
                raise zm.MasterCancelled(job["master_id"])
            job["stage"] = f"Pick one of your {len(got)} options." if len(got) > 1 else "Your option is ready."
        else:
            _draw_one(job, job["seed"], dest)
            _write_master_json(job, work, job["seed"])
            job["url"] = f"/api/file?path={_key(dest)}"
            job["stage"] = "Master ready."
        if not _dry():
            _MASTER_TIMES.append((_t.monotonic() - t_start) / max(1, len(bo.done(rec)) if rec else 1))
            del _MASTER_TIMES[:-5]
        job["state"] = "done"
    except zm.MasterCancelled:
        job["state"], job["stage"] = "cancelled", "Stopped."
    except Exception as e:  # noqa: BLE001
        job["state"], job["error"] = "error", f"Couldn't draw the master: {e}"
        job["stage"] = job["error"]


def _master_eta(cfg: dict, backend: str) -> int | None:
    """About how long a master takes: past studio runs here, else the preset's typical time; None when unknown."""
    if _dry():
        d = float(os.environ.get("OPENSOUL_MASTER_PREVIEW_DELAY", "0" if os.environ.get("OPENSOUL_SHEET_SYNC") == "1" else "1.2"))
        return max(1, round(d)) if d >= 1 else None
    if _MASTER_TIMES:
        return max(1, round(sum(_MASTER_TIMES) / len(_MASTER_TIMES)))
    t = cfg.get("typical_s") if backend == "zimage" else None
    return int(t) if t else None


@app.post("/api/master")
def make_master(
    name: str = Form("My character"),
    look: str = Form(""),
    outfit: str = Form(""),
    age: str = Form(""),
    style: str = Form(""),
    seed: int = Form(7),
    options: int = Form(1),
    pronoun: str = Form(""),
):
    """Describe your character -> one master picture (no photo needed, so no rights tick). Runs like a take: the
    reply is the job (queued/running/done/error/cancelled), polled with GET /api/master/{id} and stopped with
    POST /api/master/{id}/cancel. Preview mode draws a labelled placeholder; the studio computer runs workflow 07z
    (Z-Image-Turbo, Apache-2.0) with this variation number, or 07t when OPENSOUL_MASTER_BACKEND=qwen07t. Nothing is
    saved to a pack yet: "Try another" calls this again with the next variation, POST /api/master/{id}/save makes the pack.
    options=N (2..8; "Make 4 options", presets/text_master.json master_batch) draws seeds seed..seed+N-1 one after
    another (opensoul/best_of.py); POST /api/master/{id}/pick chooses one, the others are kept with the character."""
    import uuid

    from opensoul import best_of as bo

    from opensoul import text_master as tm
    from opensoul import zimage_master as zm

    why = tm.problem(look, outfit)
    if why:
        raise HTTPException(400, why)
    if not 0 <= seed < 2**31 - bo.MAX_N:
        raise HTTPException(400, "Pick a seed between 0 and 2147483639.")
    if not 1 <= options <= bo.MAX_N:
        raise HTTPException(400, f"Make between 1 and {bo.MAX_N} options.")
    name = _clean_name(name)
    f = tm.fields(look, outfit, age, style)
    prompt = tm.compose(**f)
    mid = uuid.uuid4().hex[:10]
    work = DATA / "outputs" / "masters" / mid
    work.mkdir(parents=True, exist_ok=True)
    cfg = zm.load_config()
    backend = cfg["backend"]
    _, smiles = tm.without_smiles(f)  # master_parts strips them too; recorded so the UI can say so
    parts = tm.master_parts(f, pronoun)  # 07z: outfit verbatim right after the subject, visible traits (cfg 1: no negative)
    look_id = parts.pop("look", "photo")
    from opensoul import looks as LK

    full = zm.master_prompt(parts.pop("description"), cfg, **parts) if backend == "zimage" else prompt
    full = LK.prompt(full, look_id)  # OS-006: an anime look draws anime, not a 'photorealistic reference photo'
    job = {"master_id": mid, "name": name, "prompt_lock": prompt, "prompt": full, "seed": seed,
           "next_seed": seed + options, "fields": f, "look_stripped": smiles, "look": look_id,
           "preview": _dry(), "backend": backend, "state": "queued", "stage": "Waiting to start…",
           "workflow": zm.WORKFLOW if backend == "zimage" else tm.WORKFLOW,
           "model": (cfg.get("model") or {}).get("name") if backend == "zimage" else "Qwen-Image-Edit-2511",
           "eta_s": _master_eta(cfg, backend),
           "label": f"Master · variation {seed}" + (" · preview" if _dry() else "")}
    if options > 1:
        job["best_of"] = bo.new_record("master", bo.seeds(seed, options))
        job["label"] = f"{options} options · variations {seed}–{seed + options - 1}" + (" · preview" if _dry() else "")
        job["eta_s"] = job["eta_s"] * options if job["eta_s"] else None
    _MASTER_JOBS[mid] = job
    if os.environ.get("OPENSOUL_SHEET_SYNC", "") == "1":
        _draw_master(job, work / "master.png")  # tests (fake ComfyUI / fake 07t)
    else:
        _start(lambda: _draw_master(job, work / "master.png"))
    return _master_json(job)


@app.get("/api/master/{mid}")
def master_status(mid: str):
    job = _MASTER_JOBS.get(mid) if _MASTER_ID.match(mid) else None
    if job is None:
        raise HTTPException(404, "That master isn't here any more. Generate it again.")
    return _master_json(job)


@app.post("/api/master/{mid}/cancel")
def cancel_master(mid: str):
    """Stop this master. On the studio computer only our own ComfyUI prompt is cancelled (opensoul.comfy_cancel)."""
    job = _MASTER_JOBS.get(mid) if _MASTER_ID.match(mid) else None
    if job is None:
        raise HTTPException(404, "That master isn't here any more.")
    if job["state"] in ("queued", "running"):
        job["cancel"] = True
        job["stage"] = "Stopping…"
    return _master_json(job)


@app.post("/api/master/{mid}/pick")
def pick_master(mid: str, seed: int = Form(...)):
    """'Use this one': the picked option becomes this job's master (master.png); every option stays on disk, and the
    seeds and the pick go into the pack with it on save (meta.origin.best_of)."""
    from opensoul import best_of as bo

    job = _MASTER_JOBS.get(mid) if _MASTER_ID.match(mid) else None
    work = DATA / "outputs" / "masters" / mid
    rec = bo.load(work / "best_of.json") if _MASTER_ID.match(mid) else None
    if rec is None:
        raise HTTPException(404, "Those options aren't here any more. Make them again.")
    try:
        bo.pick(rec, seed)
    except ValueError:
        raise HTTPException(400, "Pick one of the finished options.")
    bo.save(rec, work / "best_of.json")
    shutil.copyfile(work / rec["pick"]["file"], work / "master.png")  # a copy: the option file itself stays
    if job is None:
        raise HTTPException(404, "That master isn't here any more. Generate it again.")
    job["best_of"], job["seed"] = rec, int(seed)
    job["label"] = f"Master · variation {seed}" + (" · preview" if _dry() else "")
    _write_master_json(job, work, int(seed))
    job["url"] = f"/api/file?path={_key(work / 'master.png')}"
    return _master_json(job)


@app.post("/api/master/{mid}/save")
def save_master(mid: str, name: str = Form("")):
    """Use this master: a new pack whose refs/ref_00 is the master and whose pack.json records origin "text"
    (prompt, seed, fields). The sheet and angles then start from ref_00. An existing pack is never overwritten."""
    from opensoul.pipeline import build_character_pack

    if not _MASTER_ID.match(mid):
        raise HTTPException(404, "That master isn't here any more. Generate it again.")
    work = DATA / "outputs" / "masters" / mid
    if not (work / "master.json").is_file() or not (work / "master.png").is_file():
        raise HTTPException(404, "That master isn't here any more. Generate it again.")
    m = json.loads((work / "master.json").read_text(encoding="utf-8"))
    name = _clean_name(name or m["name"])
    target = DATA / "packs" / _pack_folder(name)  # a name in use gets the next free <name>_N folder
    if target.exists():
        target = _free_pack_folder(target)
    (DATA / "packs").mkdir(parents=True, exist_ok=True)
    build_character_pack(name, [work / "master.png"], m["prompt"], target, seed=int(m["seed"]))
    from opensoul.character_voices import ensure_voice

    from opensoul.voice_engine import available_voice_ids

    ensure_voice(DATA, name, text=m.get("prompt") or "", available=available_voice_ids(DATA))  # OS-048, OS-055
    from opensoul import best_of as bo

    rec = bo.load(work / "best_of.json")
    if rec and rec.get("pick"):
        # every option is kept with the character (options/), the picked one is also refs/ref_00
        (target / "options").mkdir(parents=True, exist_ok=True)
        for c in bo.done(rec):
            shutil.copyfile(work / c["file"], target / "options" / c["file"])
            c["file"] = f"options/{c['file']}"
        rec["pick"]["file"] = f"options/{Path(rec['pick']['file']).name}"
    else:
        rec = None
    _record_text_origin(target, m["prompt"], int(m["seed"]), m.get("fields"), master="refs/ref_00.png",
                        workflow=m.get("workflow", ""), master_prompt=m.get("master_prompt", ""), best_of=rec)
    ref = target / "refs" / "ref_00.png"
    return {"name": name, "pack_dir": str(target), "prompt_lock": m["prompt"], "seed": int(m["seed"]),
            "master_url": f"/api/file?path={_key(ref)}", "sheet_url": None, "has_images": True,
            "status": f"{name} saved from your description. Make a character sheet for six locked angles, or choose a shot."}


def _start(fn) -> None:
    import threading

    if _dry() and os.environ.get("OPENSOUL_SHEET_SYNC", "") == "1":
        fn()  # tests
    else:
        threading.Thread(target=fn, daemon=True).start()


PREVIEW_SHEET_LINE = "Preview mode: stand-in angles. Real angles are drawn and checked against the master when a studio is set up."


def _view_flag(v, dry: bool = False) -> tuple[str, str]:
    """(why a finished view needs a look, source) — ("", "") when it's fine.

    source "studio": a real problem (a real look check failed, the render failed, or the sheet left a note);
    source "preview": only a dry-run stand-in scored below the gate. The UI shows per-view warnings for studio
    flags only; a preview sheet gets one calm line (PREVIEW_SHEET_LINE) instead."""
    if getattr(v, "status", "") not in ("done", "failed"):
        return "", ""
    if v.note:
        return v.note, "studio"
    if v.status == "failed":
        return "This view didn't render.", "studio"
    if v.passed is False:
        bad = [c.get("label") or c.get("id") for c in (v.checks or []) if c.get("passed") is False]
        if dry and not bad:
            return "Preview stand-in scored below the look check (real views are checked in Studio).", "preview"
        return "Didn't pass the look check" + (f": {', '.join(map(str, bad))}." if bad else "."), "studio"
    return "", ""


def _view_json(v, dry: bool = False) -> dict:
    flag, src = _view_flag(v, dry)
    return {"id": v.id, "label": v.label, "status": v.status, "score": v.score, "passed": v.passed,
            "attempts": v.attempts, "arcface": v.arcface, "checks": v.checks, "note": v.note,
            "flagged": bool(flag), "flag_reason": flag, "flag_source": src or None,
            "url": (_file_url(Path(v.path)) if _old_design(v.path) else f"/api/file?path={_key(v.path)}") if v.path else None}


def _sheet_progress(job: dict):
    def progress(views, stage: str) -> None:
        job["stage"] = stage
        job["views"] = [_view_json(v, bool(job.get("dry_run"))) for v in views]
    return progress


def _sheet_done(job: dict, res) -> None:
    import time as _t

    job["views"] = [_view_json(v, bool(res.dry_run)) for v in res.views]
    bust = int(_t.time())
    job["sheet_url"] = _file_url(Path(res.sheet)) if _old_design(res.sheet) else f"/api/file?path={_key(res.sheet)}&v={bust}"
    _record_fields(job.get("pack_dir"), **(job.get("fields") or {"look": "", "outfit": ""}))
    job["download_url"] = f"/api/file?path={_key(res.sheet)}&download=1"
    job["state"] = "done"
    flagged = [v for v in res.views if _view_flag(v, bool(res.dry_run))[1] == "studio"]
    if flagged:
        msg = f"All six angles done. {len(flagged)} view(s) can still be wrong: click Regenerate on them."
    elif res.dry_run:
        msg = "All six angles done."
    elif not getattr(res, "checked", True):
        # OS-010: no checker model on this computer, so only the face gate ran. Say so; never claim 'checked'.
        msg = "All six angles done. OpenSoul checked the face only. Look at each view: style, outfit and glasses."
    else:
        msg = "All six angles done and checked."
    job["stage"] = msg  # a preview's "look checks run in Studio mode" line is shown once, under the views (preview_note)


@app.post("/api/sheet/{job_id}/regenerate/{view_id}")
def regenerate_sheet_view(job_id: str, view_id: str):
    """Per-view Regenerate: re-render one view with its corrections, re-check it, rebuild grid + Soul Pack."""
    from opensoul.character_sheet import load_preset, regenerate_view

    job = _SHEET_JOBS.get(job_id)
    if job is None or "work" not in job:
        raise HTTPException(404, "That sheet isn't available anymore. Make the sheet again.")
    if view_id not in {v["id"] for v in load_preset()["views"]}:
        raise HTTPException(400, "Unknown view.")
    if job["state"] == "running":
        raise HTTPException(409, "The sheet is still working. Try again in a moment.")
    job["state"], job["stage"] = "running", "Regenerating"

    def run() -> None:
        try:
            res = regenerate_view(job["work"], view_id, dry_run=_dry(), progress=_sheet_progress(job))
            _sheet_done(job, res)
        except Exception as e:
            job["state"], job["error"] = "error", f"Couldn't regenerate that view: {e}"
            job["stage"] = job["error"]

    _start(run)
    return _sheet_view_json(job)


@app.get("/api/sheet/{job_id}")
def sheet_status(job_id: str):
    job = _SHEET_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "That sheet job isn't running anymore. Make the sheet again.")
    return _sheet_view_json(job)


@app.post("/api/photos")
def make_photos(
    pack_dir: str = Form(...),
    scene: str = Form(""),
    n: int = Form(3),
    threshold: float = Form(0.78),
):
    if not _in_app_tree(pack_dir) or not Path(pack_dir).is_dir():
        raise HTTPException(400, "OpenSoul cannot find the character. Return to step 1.")
    if _dry() and Path(pack_dir).resolve() == DEMO_PACK.resolve():
        items = []
        scores = _scores_log()
        for i, u in enumerate(_demo_stills()):
            s = scores[i] if i < len(scores) else {"score": 0.9, "passed": True}
            items.append(
                {
                    "url": u,
                    "score": s.get("score"),
                    "passed": s.get("passed", True),
                    "label": "Pass" if s.get("passed", True) else "Needs a redo",
                }
            )
        return {"items": items}
    os.environ.setdefault("OPENSOUL_DRY_RUN", "1")
    if (Path(pack_dir) / "pack.json").is_file() and not _own_refs(pack_dir) and not _is_demo_pack(pack_dir):
        raise HTTPException(400, "This character has no picture yet. Generate a master or make a character sheet first.")
    kept = generate_stills(pack_dir, scene, n=n, out_dir=DATA / "outputs" / "stills", threshold=threshold)
    # Also score rejects? pipeline only returns kept — OK for now
    items = []
    for p, r in kept:
        items.append(
            {
                "url": f"/api/file?path={_key(p)}",
                "score": r.score,
                "passed": r.passed,
                "label": "Pass" if r.passed else "Needs a redo",
            }
        )
    return {"items": items}


def _bundled_script(script_id: str) -> str:
    """Text of one bundled script (content/lumi/<id>.md). An id is a single file name, never a path."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}", script_id or ""):
        return ""
    try:
        sp = (SCRIPTS / f"{script_id}.md").resolve()
        if sp.is_file() and sp.is_relative_to(SCRIPTS.resolve()):
            return sp.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return ""
    return ""


@app.post("/api/video")
def make_video(
    pack_dir: str = Form(""),
    script_id: str = Form(""),
    script_text: str = Form(""),
    still_path: str = Form(""),
):
    body = script_text
    if script_id and not script_text:
        body = _bundled_script(script_id)
    if _dry() and _poster_url():
        return {
            "poster_url": _poster_url(),
            "note": "Preview poster. Connect a studio to render the talking video.",
            "script_preview": (body or "")[:800],
        }
    if pack_dir and not _in_app_tree(pack_dir):
        raise HTTPException(400, "OpenSoul cannot find the character. Return to step 1.")
    if not still_path or not _in_app_tree(still_path) or not Path(still_path).is_file():
        raise HTTPException(400, "Choose a photo from step 2 first.")
    path = generate_talking_video(pack_dir or DATA / "packs", still_path, body or "Hello.", DATA / "outputs" / "video")
    return {"poster_url": f"/api/file?path={_key(path)}", "note": str(path), "script_preview": body[:800]}


@app.get("/api/file")
def get_file(path: str, download: int = 0):
    p = _from_key(path)
    if not _inside(p, ROOT, DATA) or _dot_path(p, ROOT, DATA):
        raise HTTPException(403, "Forbidden")  # no sibling folders (/repo_x), no .git / .venv / dotfiles
    if not p.is_file():
        raise HTTPException(404, "Not found")
    if download:
        return FileResponse(p, filename=f"opensoul_{p.name}")
    return FileResponse(p)


# Every CSS/JS file index.html loads: all of them get ?v=<hash> (P2-15: music, unified and tiles were missing).
UI_ASSETS = ("theme.css", "app.css", "storyboard.css", "music.css", "hardware.css", "models.css", "launcher.css",
             "tiles.js", "app.js", "storyboard.js", "unified.js", "music.js", "hardware.js", "models.js", "theme.js", "launcher.js")


def _asset_version() -> str:
    """Short hash of the UI files, so browsers never run a stale app.js/app.css after an update."""
    import hashlib

    h = hashlib.sha1()
    for name in UI_ASSETS:
        f = STATIC / name
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()[:10]


@app.api_route("/index.html", methods=["GET", "HEAD"], include_in_schema=False)
def index_html_redirect(request: Request):
    """Old bookmarks: always go through the versioned page (keeps ?step= etc.)."""
    from fastapi.responses import RedirectResponse

    q = request.url.query
    return RedirectResponse("/" + (f"?{q}" if q else ""), status_code=307, headers={"Cache-Control": "no-cache"})


def _first_run_pending() -> bool:
    """True until the welcome page has been finished once (launcher.json first_run_done)."""
    try:
        from opensoul import launcher

        return not launcher.load_config().get("first_run_done")
    except Exception:  # noqa: BLE001 - never block the app on a bad launcher.json
        return False


@app.api_route("/", methods=["GET", "HEAD"])
def index(request: Request):
    from fastapi.responses import HTMLResponse, RedirectResponse

    # P2-15: a first-run browser visit (also from source, not only via the launcher) starts on the welcome page.
    # Only a plain page load is sent there; any ?query (tabs, ?quick=1, ?ui=classic) opens the app as asked.
    if (not request.url.query and "text/html" in request.headers.get("accept", "")
            and request.headers.get("sec-fetch-dest", "document") == "document" and _first_run_pending()):
        return RedirectResponse("/welcome", status_code=307, headers={"Cache-Control": "no-cache"})
    v = _asset_version()
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for asset in UI_ASSETS:
        html = html.replace(f"/static/{asset}\"", f"/static/{asset}?v={v}\"")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


class _RevalidatingStatic(StaticFiles):
    """UI files: browsers must revalidate every time (ETag / Last-Modified give cheap 304s), so an
    update is never hidden behind a cached app.js, even when it is requested without ?v=."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


_include_storyboard()
from app.music_routes import router as music_router  # noqa: E402
app.include_router(music_router)
from app.hardware_routes import router as hardware_router  # noqa: E402
app.include_router(hardware_router)
from app.setup_routes import router as setup_router  # noqa: E402
app.include_router(setup_router)
from app.launcher_routes import router as launcher_router  # noqa: E402
app.include_router(launcher_router)

# Static mounts after routes
if (ROOT / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(ROOT / "assets")), name="assets")
if STATIC.is_dir():
    app.mount("/static", _RevalidatingStatic(directory=str(STATIC)), name="static")


def main():
    import uvicorn

    os.environ.setdefault("OPENSOUL_DRY_RUN", "1")
    DATA.mkdir(parents=True, exist_ok=True)
    host = serve_host()
    port = int(os.environ.get("GRADIO_SERVER_PORT") or os.environ.get("OPENSOUL_PORT", "7860"))
    uvicorn.run(app, host=host, port=port, log_level="info")


LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def serve_host() -> str:
    """OPENSOUL_HOST, but only a loopback address unless OPENSOUL_ALLOW_LAN=1: the API has no login, so a LAN
    address would show your characters to every computer on the network."""
    import sys

    host = (os.environ.get("OPENSOUL_HOST") or "127.0.0.1").strip()
    if host in LOOPBACK:
        return host
    if os.environ.get("OPENSOUL_ALLOW_LAN") == "1":
        print(f"WARNING: OpenSoul listens on {host}. It has no login: every computer on this network can use it. "
              "Add the name you type in the browser to OPENSOUL_ALLOWED_HOSTS.", file=sys.stderr)
        return host
    print(f"OPENSOUL_HOST={host} is ignored: OpenSoul listens on 127.0.0.1 only. "
          "Set OPENSOUL_ALLOW_LAN=1 to allow other computers.", file=sys.stderr)
    return "127.0.0.1"


if __name__ == "__main__":
    main()
