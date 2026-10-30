"""Storyboard API: /api/storyboard/...  (model + rules live in opensoul/storyboard.py).

Dry-run (default): Regenerate makes a clearly labelled placeholder take (the shot's picture stamped
"Preview" + the edit text, and a short clip when ffmpeg is present). Live: the same shot pipeline as
/api/shot (opensoul.shot.run_shot), in the background; the take shows "rendering" until it lands.
"""

from __future__ import annotations

import json
import os
import re

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from opensoul import storyboard as sb



def _bind_data() -> None:
    """Every storyboard request resolves stored ``data/...`` media paths against this server's DATA dir."""
    _srv()


router = APIRouter(prefix="/api/storyboard", tags=["storyboard"], dependencies=[Depends(_bind_data)])


def _srv():
    import app.server as server  # late import: tests monkeypatch server.DATA / LIBRARY

    sb.set_data_dir(server.DATA)  # stored data/... media paths resolve against THIS server's data, not the repo
    return server


def _store() -> sb.Store:
    return sb.Store(_srv().DATA / "projects")


def _err(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except sb.NotFound as e:
        raise HTTPException(404, str(e))
    except sb.StoryError as e:
        raise HTTPException(400, str(e))


def _url(p: str | None) -> str | None:
    q = sb.abs_path(p)
    return _srv()._file_url(q) if q is not None and q.is_file() else None


def _is_still(p: str | None) -> bool:
    return bool(p) and Path(p).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}


def _project_json(p: sb.Project) -> dict:
    d = p.to_dict()
    d.pop("deleted_shots", None)
    d["dry_run"] = _srv()._dry()
    d["voice_engine"] = p.tts_engine or "orpheus"  # none saved = an older story: Orpheus
    from opensoul import originality as _og

    d["avoid_default_items"] = list(_og.DEFAULT_AVOID)  # OS-068: shown under Avoid
    music = _music_shots(p.id)
    for s in d["shots"]:
        if s["id"] in music:
            s["music"] = music[s["id"]]  # OS-043: the shot sheet says what a sung shot's Final does
        for v in s["versions"]:
            v["poster_url"] = _url(v.get("poster")) or (_url(v.get("file")) if _is_still(v.get("file")) else None)
            v["video_url"] = _url(v.get("file")) if v.get("file") and not _is_still(v.get("file")) else None
            f = sb.abs_path(v.get("file"))
            v["missing"] = bool(v.get("file")) and v.get("status") == "ready" and not (f is not None and f.is_file())
        k = next((v for v in s["versions"] if v["id"] == s["keeper"]), None)
        s["keeper_poster_url"] = k["poster_url"] if k else None
        if k and k.get("video_url"):  # OS-061: the keeper's own length, for the Export cut list
            k["take_seconds"] = _take_seconds(k.get("file"))
    for loc in d.get("locations", []):
        loc["image_url"] = _url(loc.get("image"))
        loc["empty_url"] = _url(loc.get("empty"))
        loc["sheet_url"] = _url(loc.get("sheet"))
        for a in loc.get("angles", []):
            a["image_url"] = _url(a.get("image"))
        loc.update(stage_readiness(loc, d["shots"]))
    if d.get("id") == sb.DEMO_ID:  # the demo story shows review-passed pictures only (presets/demo_images.json)
        from opensoul.demo_images import apply_project

        apply_project(d)
        d["demo"] = True  # its shots follow an approved-take allow-list (Export says "no approved take")
    return d


_DUR: dict = {}


def _take_seconds(rel: str | None) -> float | None:
    """Length of a take's video in seconds (cached by path and mtime; None when it can't be read)."""
    f = sb.abs_path(rel) if rel else None
    if f is None or not f.is_file():
        return None
    key = (str(f), f.stat().st_mtime)
    if key not in _DUR:
        from opensoul import media

        try:
            _DUR[key] = round(media.duration(f), 2) or None
        except Exception:  # noqa: BLE001
            _DUR[key] = None
    return _DUR[key]


MIN_ANGLES = 2


def stage_readiness(loc: dict, shots: list[dict]) -> dict:
    """The stage-sheet checklist (like the character sheet's): what's done, what's missing, and whether the built
    sheet is older than its pictures."""
    def mtime(rel):
        f = sb.abs_path(rel) if rel else None
        return f.stat().st_mtime if f and f.is_file() else None

    with_pics = [a for a in loc.get("angles", []) if a.get("image_url")]
    sheet_t = mtime(loc.get("sheet"))
    newest = max([t for t in [mtime(loc.get("image")), mtime(loc.get("empty")), *[mtime(a.get("image")) for a in with_pics]]
                  if t] or [0])
    stale = bool(sheet_t and newest and newest > sheet_t)
    items = [
        {"id": "master", "label": "Master plate (the wide shot)", "done": bool(loc.get("image_url")), "optional": False},
        {"id": "angles", "label": f"At least {MIN_ANGLES} angles", "done": len(with_pics) >= MIN_ANGLES, "optional": False,
         "detail": f"{len(with_pics)} made" if len(with_pics) >= MIN_ANGLES else f"{len(with_pics)} of {MIN_ANGLES}"},
        {"id": "description", "label": "Set description", "done": bool((loc.get("description") or "").strip()), "optional": True},
        {"id": "empty", "label": "Empty plate (nobody in it)", "done": bool(loc.get("empty_url")), "optional": True},
        {"id": "checklist", "label": "Continuity checklist", "done": bool(loc.get("checklist")), "optional": True},
        {"id": "sheet", "label": "Stage sheet built", "done": bool(loc.get("sheet_url")) and not stale, "optional": False,
         "detail": "out of date: build it again" if stale else ""},
    ]
    # One definition of "angles" everywhere (stage row, shot picker, editor, checklist): angles that have a picture,
    # never counting the master plate.
    return {"readiness": items, "ready": all(i["done"] for i in items if not i["optional"]), "sheet_stale": stale,
            "angle_count": len(with_pics),
            "shots_using": sum(1 for s in shots if (s.get("location") or "").lower() == loc["name"].lower()),
            "rendering": sum(1 for a in loc.get("angles", []) if a.get("status") == "rendering")}


def _ensure_demo() -> None:
    try:
        sb.seed_demo(_store()) or sb.refresh_demo(_store())
        if _srv()._dry():
            sb.seed_preview_demo(_store())  # OS-001: the story that matches the Preview sample clips
    except (OSError, sb.StoryError):
        pass  # an unreadable demo file is reported by GET /projects ("broken"), never a 500


# ---------------------------------------------------------------- projects
class ShotIn(BaseModel):
    beat: str = ""
    prompt: str = ""
    characters: list[str] | None = None
    camera: str = "static"
    index: int | None = None
    line: str | None = None             # spoken line, allowed tags only (<laugh> <chuckle> <sigh> <gasp> ...)
    speaker: str | None = None          # who says it (one of characters)
    voice: str | None = None            # Orpheus voice override ("" = the speaker's own)
    lipsync: bool | None = None         # Final: render the mouth to the voice
    lipsync_backend: str | None = None  # "ltx_av" (default) | "latentsync"
    mouth_refine: bool | None = None    # opt-in LatentSync Stage 2 on camera-locked takes (may pale lips)
    face_box: list[int] | None = None   # [x, y, w, h] of the speaker's face on frame 0 ([] clears)
    seconds: float | None = None        # planned length of the shot, 0 = automatic (OS-059, OS-061)
    kind: str | None = None             # OS-063: "scene" (default) | "card"
    card_title: str | None = None
    card_sub: str | None = None
    card_bg: str | None = None


class ProjectIn(BaseModel):
    title: str = ""
    character: str = ""                 # optional lead; new shots cast them by default
    template: str = "blank"             # "blank" | a template id from GET /templates
    shots: list[ShotIn] | None = None   # e.g. the edited result of POST /script/split


class ProjectPatch(BaseModel):
    title: str | None = None
    character: str | None = None
    tts_engine: str | None = None       # orpheus | kokoro | chatterbox | voxcpm2 (opensoul/voice_engine.py)
    look: str | None = None             # "" (photo) | anime | toon3d | illustration (opensoul/looks.py)
    fix_camera: bool | None = None      # OS-017: re-render when the camera move reads wrong
    avoid: str | None = None            # OS-068: what pictures and takes must not show (comma list)
    avoid_defaults: bool | None = None  # OS-068: the built-in list of famous-design traits (on by default)


def _camera_ids() -> set[str]:
    from opensoul.presets import load_presets

    return {c["id"] for c in load_presets()["camera"]}


@router.get("/projects")
def list_projects():
    _ensure_demo()
    projects, broken = _store().scan()
    return {"projects": [{"id": p.id, "title": p.title, "character": p.character, "shots": len(p.shots),
                          "demo": p.id == sb.DEMO_ID, "updated": p.updated,
                          "preview_demo": p.id == sb.PREVIEW_DEMO_ID} for p in projects],
            "preview": _srv()._dry(),
            "broken": broken}


@router.post("/projects")
def create_project(req: ProjectIn):
    """New story: blank, from a template, or from a list of shots (Start from a script)."""
    st = _store()
    from opensoul import migrate

    if migrate.is_shorts(req.title) and not req.shots and (req.template or "blank") == "blank":
        return _project_json(migrate.ensure_project(st))  # Shorts: one story, id quick-shots, 9:16
    if req.shots:
        for x in req.shots:
            _check_camera(x.camera)
        _err(sb.check_shots, [x.model_dump() for x in req.shots])  # a bad shot never leaves an empty story behind
        p = _err(st.create_project, req.title, req.character)
        _err(st.add_shots, p.id, [x.model_dump() for x in req.shots])
        return _project_json(st.load(p.id))
    p = _err(sb.create_from_template, st, req.template or "blank", req.title, req.character, _camera_ids())
    return _project_json(p)


@router.patch("/projects/{pid}")
def patch_project(pid: str, req: ProjectPatch):
    return _project_json(_err(_store().update_project, pid, req.title, req.character, req.tts_engine, req.look,
                                  req.fix_camera, req.avoid, req.avoid_defaults))


@router.get("/looks")
def list_looks():
    """The art looks a story can use (OS-006)."""
    from opensoul import looks

    return {"looks": looks.choices(), "default": looks.DEFAULT}


@router.get("/templates")
def templates():
    return {"templates": [{"id": t["id"], "title": t["title"], "blurb": t["blurb"], "shots": len(t["shots"]),
                           "beats": [x.get("beat", "") for x in t["shots"]]} for t in sb.list_templates()]}


class ScriptIn(BaseModel):
    text: str = ""


@router.post("/script/split")
def split_script(req: ScriptIn):
    """Suggest shots from a pasted script (rule-based, local; nothing is saved until the story is made)."""
    from opensoul.script_split import split_script as split

    if not req.text.strip():
        raise HTTPException(400, "Paste a script first.")
    return split(req.text, [c["name"] for c in _cast_library()])


@router.get("/projects/{pid}")
def get_project(pid: str):
    if pid == sb.DEMO_ID:
        _ensure_demo()
    return _project_json(_err(_store().load, pid))


# ---------------------------------------------------------------- shots
class ShotsIn(BaseModel):
    shots: list[ShotIn]


class RestoreIn(BaseModel):
    index: int | None = None


class ShotPatch(BaseModel):
    beat: str | None = None
    prompt: str | None = None
    characters: list[str] | None = None
    camera: str | None = None
    camera_moves: list[str] | None = None  # up to 3 stacked moves, in order (rules: presets/camera_rules.json)
    location: str | None = None
    stage_angle: str | None = None
    line: str | None = None             # spoken line, allowed tags only (<laugh> <chuckle> <sigh> <gasp> ...)
    speaker: str | None = None          # who says it (one of characters)
    voice: str | None = None            # Orpheus voice override ("" = the speaker's own)
    lipsync: bool | None = None         # Final: render the mouth to the voice
    lipsync_backend: str | None = None  # "ltx_av" (default) | "latentsync"
    mouth_refine: bool | None = None    # opt-in LatentSync Stage 2 on camera-locked takes (may pale lips)
    face_box: list[int] | None = None   # [x, y, w, h] of the speaker's face on frame 0 ([] clears)
    seconds: float | None = None        # planned length of the shot, 0 = automatic (OS-059, OS-061)
    trim_start: float | None = None     # OS-061: the export uses the keeper from this second on
    kind: str | None = None             # OS-063: "scene" | "card" (a title or end card drawn on this computer)
    card_title: str | None = None
    card_sub: str | None = None
    card_bg: str | None = None          # black | white | night | red | #rrggbb


class LocationIn(BaseModel):
    image: str | None = None         # path of the master plate (repo-relative or absolute)
    from_version: str | None = None  # or "<shot id>/<version id>": use that take's still / poster as the plate
    description: str | None = None
    empty: str | None = None         # path of the empty plate (same angle as the master, nobody in it)
    checklist: list[str] | None = None


class AngleIn(BaseModel):
    image: str | None = None         # an existing picture of this angle
    from_version: str | None = None  # or "<shot id>/<version id>"
    note: str | None = None          # what the angle sees
    generate: bool = False           # make it from the master/empty plate (Qwen-Image-Edit, local)
    seed: int | None = None
    rename: str | None = None        # new name for this angle (shots that use it follow)


class OrderIn(BaseModel):
    order: list[str]


class MoveIn(BaseModel):
    delta: int


def _check_camera(cam: str | None) -> None:
    if cam is None:
        return
    from opensoul.presets import load_presets

    if cam not in {c["id"] for c in load_presets()["camera"]}:
        raise HTTPException(400, f"Unknown camera move {cam!r}.")


@router.post("/projects/{pid}/shots")
def add_shot(pid: str, req: ShotIn):
    _check_camera(req.camera)
    st = _store()
    _err(st.add_shot, pid, req.beat, req.prompt, req.characters, req.camera, req.index,
         **req.model_dump(include=set(sb.DIALOGUE_FIELDS) | set(sb.CARD_FIELDS)))
    return _project_json(st.load(pid))


@router.post("/projects/{pid}/shots/batch")
def add_shots(pid: str, req: ShotsIn):
    """Append several shots (e.g. Add from a script into an existing story)."""
    for x in req.shots:
        _check_camera(x.camera)
    st = _store()
    _err(st.add_shots, pid, [x.model_dump() for x in req.shots])
    return _project_json(st.load(pid))


@router.post("/projects/{pid}/shots/{sid}/restore")
def restore_shot(pid: str, sid: str, req: RestoreIn):
    """Undo a delete: the shot and all its takes come back."""
    return _project_json(_err(_store().restore_shot, pid, sid, req.index))


@router.patch("/projects/{pid}/shots/{sid}")
def patch_shot(pid: str, sid: str, req: ShotPatch):
    _check_camera(req.camera)
    st = _store()
    _err(st.update_shot, pid, sid, **req.model_dump())
    return _project_json(st.load(pid))


@router.put("/projects/{pid}/locations/{name}")
def put_location(pid: str, name: str, req: LocationIn):
    """Add or update a location (set): a master-plate picture + a fixed set description. Start frames of shots
    set there are edited from the plate (picture 1), so the place looks the same in every shot."""
    st = _store()
    p = _err(st.load, pid)
    image = req.image
    if req.from_version:
        sid, _, vid = req.from_version.partition("/")
        v = _err(_err(p.shot, sid).version, vid)
        image = v.file if _is_still(v.file) else v.poster
        if not image:
            raise HTTPException(400, "That take has no still to use as the plate.")
    if image is not None:
        f = sb.abs_path(image)
        if not f or not f.is_file():
            raise HTTPException(400, "OpenSoul cannot find the plate picture.")
        _need_picture(f, "plate picture")
        image = sb.rel_path(f)
    empty = None
    if req.empty is not None:
        f = sb.abs_path(req.empty) if req.empty else None
        if req.empty and (not f or not f.is_file()):
            raise HTTPException(400, "OpenSoul cannot find the empty plate picture.")
        if f:
            _need_picture(f, "empty plate picture")
        empty = sb.rel_path(f) if f else ""
    _err(st.set_location, pid, name, image, req.description, empty, req.checklist)
    return _project_json(st.load(pid))


def _need_picture(f: Path, what: str) -> None:
    """400 (not a 500 later in the angle / stage-sheet render) when the file isn't an image we can read."""
    try:
        from PIL import Image

        with Image.open(f) as im:
            im.verify()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, f"The {what} isn't an image we can read. Use a JPG or PNG.")


def _picture(p, image, from_version, what="picture"):
    if from_version:
        sid, _, vid = from_version.partition("/")
        v = _err(_err(p.shot, sid).version, vid)
        image = v.file if _is_still(v.file) else v.poster
        if not image:
            raise HTTPException(400, f"That take has no still to use as the {what}.")
    if image is None:
        return None
    f = sb.abs_path(image)
    if not f or not f.is_file():
        raise HTTPException(400, f"OpenSoul cannot find the {what}.")
    _need_picture(f, what)
    return sb.rel_path(f)


@router.put("/projects/{pid}/locations/{name}/angles/{angle}")
def put_stage_angle(pid: str, name: str, angle: str, req: AngleIn):
    """Add or update one angle of a stage sheet: from a picture, a take, or generated from the master plate."""
    st = _store()
    p = _err(st.load, pid)
    loc = p.location(name)
    if loc is None:
        raise HTTPException(404, "That stage isn't in this story.")
    from opensoul import stage_sheet

    if req.rename is not None:
        _err(st.rename_stage_angle, pid, loc.name, angle, req.rename)
        angle = " ".join(req.rename.split())
        if not (req.generate or req.image or req.from_version or req.note is not None):
            return _project_json(st.load(pid))
        p = st.load(pid)
        loc = p.location(name)
    note = req.note
    if note is None and not loc.angle(angle):
        note = stage_sheet.angle_note(angle)
    image = _picture(p, req.image, req.from_version, "angle picture")
    if not req.generate:
        _err(st.set_stage_angle, pid, loc.name, angle, image, note)
        return _project_json(st.load(pid))
    # Generate: check everything (and in preview, make the picture) BEFORE the angle row is saved, so a refusal or a
    # failed render never leaves an empty angle behind.
    base = sb.abs_path(loc.empty or loc.image) if (loc.empty or loc.image) else None
    if base is None or not base.is_file():
        raise HTTPException(400, "Give the stage a master plate first. OpenSoul makes its angles from it.")
    clean = " ".join(str(angle or "").split())[:60]
    if not clean:
        raise HTTPException(400, "Give the angle a name, e.g. \"behind the counter\".")
    old = loc.angle(clean)
    if old is None and len(loc.angles) >= st.MAX_ANGLES:
        raise HTTPException(400, f"A stage sheet holds up to {st.MAX_ANGLES} angles.")
    a_name = old.name if old else clean
    a_note = note if note is not None else (old.note if old else "")
    import random

    seed = req.seed if req.seed is not None else random.randint(1, 2**31 - 2)
    dest = st.project_dir(pid) / "stages" / _slug(loc.name) / f"{_slug(a_name)}_s{seed}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    prompt = stage_sheet.angle_prompt(a_note or stage_sheet.angle_note(a_name) or a_name, loc.description, look=p.look)
    srv = _srv()
    if srv._dry():
        from opensoul import scene

        try:
            scene.preview_frame([str(base)], dest, aspect=p.aspect, title=a_name,
                                label=f"{loc.name} · angle preview (Preview mode)")
        except Exception as e:  # noqa: BLE001  an unreadable plate etc.: a plain 400, nothing saved
            raise HTTPException(400, f"Couldn't make that angle from the master plate: {e}")
        _err(st.set_stage_angle, pid, loc.name, a_name, sb.rel_path(dest), note, "", "")
    else:
        _err(st.set_stage_angle, pid, loc.name, a_name, image, note, "rendering", "")  # the row shows while it renders

        def run() -> None:
            from opensoul import scene

            try:
                scene.compose_frame([str(base)], prompt, seed, dest, aspect=p.aspect)
                st.set_stage_angle(pid, loc.name, a_name, sb.rel_path(dest), None, "", "")
            except Exception as e:  # noqa: BLE001  keep the angle, say why
                st.set_stage_angle(pid, loc.name, a_name, None, None, "failed", f"Couldn't make this angle: {e}")
        srv._start(run)
    return _project_json(st.load(pid))


@router.delete("/projects/{pid}/locations/{name}/angles/{angle}")
def delete_stage_angle(pid: str, name: str, angle: str):
    return _project_json(_err(_store().remove_stage_angle, pid, name, angle))


@router.get("/stage/angle-suggestions")
def angle_suggestions():
    from opensoul import stage_sheet

    return {"angles": stage_sheet.GENERIC_ANGLES, "max": sb.Store.MAX_ANGLES, "min": MIN_ANGLES}


@router.post("/projects/{pid}/locations/{name}/upload")
async def upload_stage_picture(pid: str, name: str, role: str = Form("master"), angle: str = Form(""),
                               consent: bool = Form(False), description: str | None = Form(None),
                               image: UploadFile | None = File(default=None)):
    """Upload a plate: the master (a new stage starts here), the empty plate, or one angle's picture."""
    st = _store()
    p = _err(st.load, pid)
    if role not in ("master", "empty", "angle"):
        raise HTTPException(400, "Pick master plate, empty plate or angle.")
    if image is None or not image.filename:
        raise HTTPException(400, "Choose a picture of the place.")
    if not consent:
        raise HTTPException(400, "Please confirm you own this picture or have permission to use it.")
    if role != "master" and p.location(name) is None:
        raise HTTPException(404, "That stage isn't in this story.")
    if role == "angle" and not " ".join(angle.split()):
        raise HTTPException(400, "Give the angle a name, e.g. \"behind the counter\".")
    data = await image.read()
    if not data:
        raise HTTPException(400, "That file is empty. Pick a picture and try again.")
    import uuid

    folder = st.project_dir(pid) / "stages" / _slug(name)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"upload_{role}_{uuid.uuid4().hex[:8]}{Path(image.filename).suffix.lower() or '.png'}"
    dest.write_bytes(data)
    try:
        _need_picture(dest, "picture")
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    rel = sb.rel_path(dest)
    if role == "master":
        _err(st.set_location, pid, name, rel, description)
    elif role == "empty":
        _err(st.set_location, pid, name, None, None, rel)
    else:
        loc = st.load(pid).location(name)
        _err(st.set_stage_angle, pid, loc.name, angle, rel,
             None if loc.angle(angle) else __import__("opensoul.stage_sheet", fromlist=["x"]).angle_note(angle), "", "")
    return _project_json(st.load(pid))


@router.post("/projects/{pid}/locations/{name}/sheet")
def make_stage_sheet(pid: str, name: str):
    """Render the stage sheet image (master, empty plate, every angle, checklist) for checking by eye."""
    from opensoul import stage_sheet

    st = _store()
    p = _err(st.load, pid)
    loc = p.location(name)
    if loc is None or not loc.image:
        raise HTTPException(400, "Give the stage a master plate first.")
    ok = lambda x: x and sb.abs_path(x) and sb.abs_path(x).is_file()
    dest = st.project_dir(pid) / "stages" / _slug(loc.name) / "stage_sheet.jpg"
    stage_sheet.build_sheet(sb.abs_path(loc.image), [(a.name, sb.abs_path(a.image)) for a in loc.angles if ok(a.image)],
                            dest, empty=sb.abs_path(loc.empty) if ok(loc.empty) else None, title=loc.name,
                            checklist=loc.checklist)
    _err(st.set_location, pid, loc.name, sheet=sb.rel_path(dest))
    return _project_json(st.load(pid))


def _slug(x: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", x.lower()).strip("_")[:40] or "stage"


@router.delete("/projects/{pid}/locations/{name}")
def delete_location(pid: str, name: str):
    return _project_json(_err(_store().remove_location, pid, name))


@router.post("/projects/{pid}/reorder")
def reorder(pid: str, req: OrderIn):
    return _project_json(_err(_store().reorder, pid, req.order))


@router.post("/projects/{pid}/shots/{sid}/move")
def move(pid: str, sid: str, req: MoveIn):
    return _project_json(_err(_store().move_shot, pid, sid, req.delta))


@router.delete("/projects/{pid}/shots/{sid}")
def delete_shot(pid: str, sid: str, confirm: int = 0):
    return _project_json(_err(_store().delete_shot, pid, sid, bool(confirm)))


# ---------------------------------------------------------------- takes
class RegenIn(BaseModel):
    edit: str = ""
    seed: int | None = None
    from_version: str | None = None
    quality: str = "draft"   # "draft" (fast preview, no lip-sync) | "final" (full render)
    lipsync: bool | None = None          # this take only (default: the shot's setting)
    lipsync_backend: str | None = None   # this take only: "ltx_av" | "latentsync"


class FinalIn(BaseModel):
    version_id: str | None = None  # default: the shot's keeper


class KeeperIn(BaseModel):
    version_id: str


def _base_still(p: sb.Project, s: sb.Shot, from_vid: str | None) -> Path | None:
    """Picture to start the new take from: the chosen take's still, else the current character's own picture.

    Never the demo character's pictures for anyone else (fingerprinted in server._is_demo_image)."""
    srv = _srv()
    demo_ok = srv._clean_name(p.character).lower() == srv.DEMO_NAME.lower()
    order = []
    if from_vid:
        order.append(s.version(from_vid))
    if s.keeper_version():
        order.append(s.keeper_version())
    order += list(reversed(s.versions))
    for v in order:
        if v is None or v.kind == "preview":  # a dry-run take is already stamped: never stamp a stamp again
            continue
        for cand in (v.poster, v.file):
            q = sb.abs_path(cand) if _is_still(cand) else None
            if q and q.is_file() and (demo_ok or not srv._is_demo_image(q)):
                return q
    look = srv._character_look(p.character, None)
    still = look.get("still")
    if still is not None and (demo_ok or not srv._is_demo_image(still)):
        return Path(still)
    return None


def _stamp(base: Path | None, dest: Path, character: str, take: int, edit: str, size: tuple[int, int]) -> Path:
    """Dry-run placeholder still: the shot's own picture, softened, with a clear PREVIEW label."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

    w, h = size
    if base is not None:
        img = ImageOps.fit(Image.open(base).convert("RGB"), size)
        img = img.filter(ImageFilter.GaussianBlur(1.2))
    else:
        img = Image.new("RGB", size, "#E8E8ED")
    over = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    try:
        big, small = ImageFont.load_default(size=max(18, h // 22)), ImageFont.load_default(size=max(14, h // 34))
    except TypeError:
        big = small = ImageFont.load_default()
    pad = max(24, w // 18)

    def wrap(text: str, font, width: int, lines: int) -> list[str]:
        """Word-wrap to the measured width; the last line ends in an ellipsis if the text is longer."""
        out, cur = [], ""
        for word in text.split():
            t = f"{cur} {word}".strip()
            if d.textlength(t, font=font) <= width:
                cur = t
                continue
            if cur:
                out.append(cur)
            cur = word
            if len(out) == lines:
                break
        if cur and len(out) < lines:
            out.append(cur)
        if len(out) == lines and " ".join(out) != " ".join(text.split()):
            last = out[-1]
            while last and d.textlength(last + "…", font=font) > width:
                last = last[:-1]
            out[-1] = last.rstrip() + "…"
        return out

    # Everything baked in sits in the bottom band, so the app's own label (top left) and Keeper pill (top right)
    # never cover it.
    head = wrap(f"PREVIEW · v{take} · {character}", big, w - 2 * pad, 2)
    text = (edit or "Another take, same prompt").strip()
    sub = ["Placeholder take (Preview mode)", *wrap("Change: " + text, small, w - 2 * pad, 3)]
    lh_big, lh_small = int(big.size * 1.25) if hasattr(big, "size") else 22, int(small.size * 1.3) if hasattr(small, "size") else 16
    band = pad + len(head) * lh_big + len(sub) * lh_small + pad // 2
    top = h - band
    d.rectangle((0, top, w, h), fill=(0, 0, 0, 150))
    y = top + pad // 2
    for line in head:
        d.text((pad, y), line, fill="white", font=big)
        y += lh_big
    for line in sub:
        d.text((pad, y), line, fill=(235, 235, 240), font=small)
        y += lh_small
    out = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest, quality=90)
    return dest


_SAYS_QUOTE = re.compile(r"\b[A-Z][\w'’-]*(?:[ \t]+[A-Z][\w'’-]*){0,3}\s+(?:says|said|asks|asked|shouts|"
                         r"whispers|replies|yells|tells \w+)\s*:?\s*[“\"][^”\"]*[”\"]\s*[.!?]?")
_LONG_QUOTE = re.compile(r"[“\"]([^”\"]*\s[^”\"]*\s[^”\"]*)[”\"]")  # three or more words in quotes


def _no_speech(text: str) -> str:
    """OS-052: spoken words are not drawn. 'Aldric says: “…”' and quoted lines of three or more words are taken out of
    the picture prompt (Qwen painted them as garbled text on screens). Short quoted titles stay."""
    out = _LONG_QUOTE.sub("", _SAYS_QUOTE.sub("", text or ""))
    return " ".join(out.split()).replace(" .", ".").replace(" ,", ",")


def _shot_prompt(p: sb.Project, s: sb.Shot) -> str:
    """The shot description a render uses: for the demo story, the script-matched text (presets/demo_images.json).
    Spoken words are taken out (OS-052)."""
    if p.id != sb.DEMO_ID:
        return _no_speech(s.prompt)
    from opensoul.demo_images import shot_text

    return shot_text(p.id, s.beat, s.prompt)


_MOUTH_SHUT = re.compile(r"\b(mouth (?:is |stays |kept )?closed|closed (?:mouth|lips)|lips (?:closed|shut|together|sealed)|"
                         r"keeps? (?:her|his|their) mouth closed|(?:does not|doesn't|do not|don't|not) (?:talk|speak|sing|"
                         r"laugh|open (?:her|his|their) mouth))\b", re.I)
_MOUTH_OPEN = re.compile(r"\b(laugh\w*|talk\w*|speak\w*|sing\w*|shout\w*|yell\w*|scream\w*|cheer\w*|open[- ]mouth\w*|"
                         r"mouth (?:wide )?open|grin\w*)\b", re.I)
_NOT_X = re.compile(r"\b(?:no|without|not|never|remove|drop)\s+(?:any\s+|the\s+|a\s+)?([a-z][a-z-]{2,})", re.I)


def _says_no(clause: str, word: str) -> bool:
    """OS-066: 'no people in frame' agrees with a change that says 'no people'; it is not a clash."""
    return bool(re.search(rf"\b(?:no|without|not|never)\s+(?:any\s+|the\s+|a\s+)?{re.escape(word)}", clause))


def _merge_edit(text: str, edit: str) -> tuple[str, list[str]]:
    """The shot text with the user's change (OS-037). The change goes last and wins: clauses of the shot text that
    say the opposite (an open, laughing mouth when the change asks for closed lips; 'X' when it says 'no X') are
    left out. Returns (prompt, the clauses that were left out)."""
    edit = " ".join((edit or "").split())
    if not edit:
        return text, []
    clauses = [c for c in re.split(r"(?<=[.;,])\s+", text or "") if c.strip()]
    banned = [w.lower() for w in _NOT_X.findall(edit) if w.lower() not in {"one", "more", "less", "longer", "too"}]
    shut = bool(_MOUTH_SHUT.search(edit))
    keep, dropped = [], []
    for c in clauses:
        low = c.lower()
        clash = (shut and _MOUTH_OPEN.search(c) and not _MOUTH_SHUT.search(c)) or any(
            re.search(rf"\b{re.escape(w)}", low) and not _says_no(low, w) for w in banned)
        (dropped if clash else keep).append(c)
    body = " ".join(keep).strip().rstrip(",;")
    return (f"{body} Most important, and it wins over anything above: {edit}").strip(), [c.strip(" ,;.") for c in dropped]


_MOUTH_WORDS = re.compile(r"\b(mouth\w*|lips?|lip-?sync\w*|teeth|tooth|jaw\w*|tongue|syllables?|vowels?|"
                          r"articulat\w*|mutes?|silent|silence)\b", re.I)


def _talk_edit(s: sb.Shot, edit: str) -> tuple[str, list[str]]:
    """OS-060: on a shot with a spoken line the voice moves the mouth. Sentences of the change that talk about the
    mouth, lips, teeth or jaw are left out (they turned the talking off in shot 20 v4). Returns (the change that is
    used, the parts that were left out)."""
    edit = " ".join((edit or "").split())
    if not edit or not (s.line and s.lipsync):
        return edit, []
    parts = [x for x in re.split(r"(?<=[.;!?])\s+", edit) if x.strip()]
    keep = [x for x in parts if not _MOUTH_WORDS.search(x)]
    left = [x.strip(" .;!?") for x in parts if _MOUTH_WORDS.search(x)]
    return " ".join(keep).strip(), left


def _full_prompt(p: sb.Project, s: sb.Shot, edit: str) -> str:
    """Look lock of everyone cast in the shot (from the user's library), then the shot, then the edit (it wins)."""
    cast_, _ = _shot_cast(s, pictures_only=False)
    locks = [c.get("prompt_lock", "") for c in cast_ if c.get("prompt_lock")]
    if not locks and p.character and not s.characters:
        lib = _srv()._library(p.character)
        locks = [(lib or {}).get("prompt_lock", "")]
    shot_text, _ = _merge_edit(_shot_prompt(p, s).strip(), _talk_edit(s, edit)[0])
    return " ".join(x for x in [*locks, shot_text] if x)


def _frame_mismatch(s: sb.Shot, base_vid: str | None) -> str:
    """OS-042: a note when What happens changed after the start frame was made (the video then adds what the frame
    does not show)."""
    v = next((x for x in s.versions if x.id == base_vid), None) if base_vid else None
    if v is None or v.kind not in ("frame", "concept") or not v.prompt:
        return ""
    now = " ".join((s.prompt or "").split())
    if not now or now in " ".join(v.prompt.split()):
        return ""
    return (f"What happens changed after {v.id} was made. The video can add actions that {v.id} does not show. "
            "Make a new start frame if the take looks wrong.")


QUALITY_LABEL = {"draft": "Draft", "final": "Final"}


def _quality(q: str | None) -> str:
    q = (q or "draft").strip().lower()
    if q not in QUALITY_LABEL:
        raise HTTPException(400, "Quality must be Draft or Final.")
    return q


@router.post("/projects/{pid}/shots/{sid}/regenerate")
def regenerate(pid: str, sid: str, req: RegenIn):
    """Always a NEW take (v<n+1>); earlier takes stay. The keeper stays too, except that a video made from the
    keeper start frame becomes the keeper when it is ready (OS-026)."""
    st = _store()
    p = _err(st.load, pid)
    s = _err(p.shot, sid)
    _not_a_card(s)
    if req.from_version:
        _err(s.version, req.from_version)
    edit = (req.edit or "").strip()[:500]
    import random

    seed = req.seed if req.seed is not None else random.randint(1, 2**31 - 2)
    base = _base_still(p, s, req.from_version)
    if req.lipsync is not None:
        s.lipsync = bool(req.lipsync)
    if req.lipsync_backend is not None:
        s.lipsync_backend = _err(sb.clean_dialogue, {"lipsync_backend": req.lipsync_backend})["lipsync_backend"]
    based_on = req.from_version or s.keeper
    bv = next((x for x in s.versions if x.id == based_on), None) if based_on else None
    # OS-026: animating the keeper start frame makes the video the keeper when it is ready.
    keep = bool(bv and based_on == s.keeper and bv.kind in ("frame", "concept"))
    return _make_take(pid, p, s, prompt=_full_prompt(p, s, edit), edit=edit, seed=seed, base=base,
                      based_on=based_on, quality=_quality(req.quality), keep_when_ready=keep,
                      extra_notes=[n for n in (_frame_mismatch(s, based_on), _dropped_note(s, edit),
                                               __import__("opensoul.originality", fromlist=["x"]).note(f"{s.prompt} {edit}")) if n])


@router.post("/projects/{pid}/shots/{sid}/final")
def make_final(pid: str, sid: str, req: FinalIn):
    """Re-render a chosen take (default: the keeper) at Final quality: same prompt, seed and start picture.

    A new take as always; the draft stays. The final take becomes the keeper once it is ready only if
    the draft it came from was the keeper."""
    st = _store()
    p = _err(st.load, pid)
    s = _err(p.shot, sid)
    vid = req.version_id or s.keeper
    if not vid:
        raise HTTPException(400, "Pick a keeper take first.")
    v = _err(s.version, vid)
    if v.kind in ("concept", "frame"):
        raise HTTPException(400, "That take is a still. Make a Draft video take from it first.")
    base = sb.abs_path((v.settings or {}).get("base_image")) or _base_still(p, s, vid)
    seed = v.seed if v.seed is not None else 42
    return _make_take(pid, p, s, prompt=v.prompt or _full_prompt(p, s, ""), edit=v.edit, seed=seed, base=base,
                      based_on=vid, quality="final", keep_when_ready=(s.keeper == vid))


# ---------------------------------------------------------------- dialogue (all lip-sync logic lives in opensoul/lipsync.py)
def _speaker(s: sb.Shot) -> str:
    return s.speaker or (s.characters[0] if len(s.characters) == 1 else "")


def _speaker_pack(who: str) -> dict:
    """The speaker's saved pack.json ({} when there is none or it can't be read)."""
    if not who:
        return {}
    try:
        c = _resolve_pack(who)
        return json.loads((Path(c["pack_dir"]) / "pack.json").read_text()) if c else {}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def _speaker_pronoun(who: str) -> str:
    """The speaker's pronoun from their saved pack ("pronoun"/"pronouns", top level or meta), else 'they'."""
    from opensoul import lipsync as L

    return L.pronoun_from_meta(_speaker_pack(who)) if who else L.DEFAULT_PRONOUN


def _shot_voice(s: sb.Shot) -> tuple[str, str]:
    """(voice id, where it came from): the shot's override, else the speaker's own voice (one resolver for all)."""
    from opensoul.character_voices import voice_for_shot

    return voice_for_shot(_srv().DATA, _speaker(s), s.voice or None)


def _voice_label_fields(who: str) -> dict:
    """The speaker's pack voice_label (lip-sync metadata, read only) and its canonical id; the TTS voice is
    ``voice`` (character_voices), never this."""
    from opensoul import lipsync as L

    vl = L.voice_label_of(_speaker_pack(who)) if who else {}
    return {"voice_label": vl.get(L.VOICE_LABEL_KEY), "voice_canonical": vl.get("voice_canonical")}


def _listener(s: sb.Shot, who: str) -> str:
    """Who the speaker's eyes hold on (off-lens, in the scene): the other character, or the others ('Ren and Ivy',
    'Ren, Ivy and Max'); '' only when nobody else is in the shot (then the camera)."""
    others = [c for c in s.characters if c and c != who]
    return others[0] if len(others) == 1 else ", ".join(others[:-1]) + f" and {others[-1]}" if others else ""


def _line_ref(s: sb.Shot, position: int | None) -> dict:
    """Where the shot's script line id comes from (opensoul.lipsync.resolve_line_id): its explicit ``line_id``, else
    'lNN' in its beat name or id, else in the wav name (known at render time), else its position in the story."""
    return {"line": getattr(s, "line_id", "") or "", "names": [s.beat, s.id], "position": position}


def _position(p, s: sb.Shot) -> int | None:
    return next((i + 1 for i, x in enumerate(p.shots) if x.id == s.id), None)


def _voice_engine(who: str, project_engine: str | None) -> tuple[str, dict | None, str]:
    """(engine, reference clip, note) for the speaker's lines in this story (opensoul.voice_engine.resolve). VoxCPM2
    without a usable clip falls back to Orpheus and the note says so; for Chatterbox a clip that can't be used
    (no consent / provenance) stops the take with its plain message."""
    from opensoul import voice_engine as VE

    pack = _speaker_pack(who) if who else {}
    engine = VE.engine_for(project_engine, pack)
    c = _resolve_pack(who) if who and engine in VE.CLONING else None
    try:
        engine, ref, note = VE.resolve(project_engine, pack, c["pack_dir"] if c else None, who=who)
    except VE.VoiceRefError as e:
        raise HTTPException(400, str(e))
    engines = VE.studio_engines()
    if engines is not None and not engines.get(engine):  # OS-054: never send a voice engine the studio doesn't have
        alt = next((e for e in ("kokoro", "orpheus") if engines.get(e)), None)
        if alt is None:
            raise HTTPException(400, "Your studio has no voice engine that OpenSoul can use (Kokoro or Orpheus). "
                                     "Install one on the studio, then try again.")
        note = (f"{VE.LABELS[engine]} isn't on your studio, so {who or 'the line'} is spoken with {VE.LABELS[alt]}. "
                "To change it, open Voices > Advanced.")
        engine, ref = alt, None
    return engine, ref, note


def _studio_voice(engine: str, voice: str) -> tuple[str, str]:
    """OS-055: (voice, note). With Kokoro on a studio, a voice whose file isn't there is replaced by one of the same
    gender that is; the note says so. No voice of that gender: a plain 400 before anything is queued."""
    if engine != "kokoro":
        return voice, ""
    from opensoul import studio_info
    from opensoul import voice_engine as VE

    have = studio_info.kokoro_voices(_srv().DATA)
    alt = VE.kokoro_substitute(voice, have)
    if alt == voice:
        return voice, ""
    if alt is None:
        raise HTTPException(400, f"The voice {voice.title()} isn't on your studio, and no voice like it is. "
                                 "Pick another voice under Voices.")
    return alt, (f"The voice {voice.title()} isn't on your studio, so this take uses {alt.title()}. "
                 "To keep it, pick it under Voices.")


def _scorer_ready() -> bool:
    """OS-057: True only when the external lip-sync scorer is set up (best-of needs it to pick a take)."""
    from opensoul import lipsync as L

    return L.scorer_enabled()


def _dialogue(s: sb.Shot, *, prompt: str, quality: str, seed: int, size: tuple[int, int],
              i2v_stage: dict | None = None, position: int | None = None,
              project_engine: str | None = None) -> dict | None:
    """The render plan for a shot's spoken line (None when it has no line). ``position``: the shot's 1-based place in
    the story, the last fallback for its script line id (grin_review_only, see _line_ref)."""
    if not s.line:
        return None
    from opensoul import lipsync as L

    voice, voice_from = _shot_voice(s)
    who = _speaker(s)
    engine, ref, voice_note = _voice_engine(who, project_engine)
    voice, swap = _studio_voice(engine, voice)
    voice_note = " ".join(x for x in (voice_note, swap) if x)
    w, h = (1280, 704) if size[0] > size[1] else (704, 1280)
    want_sync = s.lipsync and quality == "final"
    stages, notes, mode = L.dialogue_stages(
        line=s.line, voice=voice, quality=quality if want_sync else "draft", backend=s.lipsync_backend, prompt=prompt,
        speaker=who, seed=seed, width=w, height=h, latentsync_installed=L.latentsync_installed(),
        face_box=s.face_box, i2v_stage=i2v_stage, faces=max(1, len(s.characters)), pronoun=_speaker_pronoun(who),
        best_of=L.best_of_for(_speaker_pack(who)) if who else 1,
        mouth_refine=bool(getattr(s, "mouth_refine", False)) or None,  # per-shot opt-in, else OPENSOUL_MOUTH_REFINE  # best-of seeds: rebuilt characters (setting)
        line_ref=_line_ref(s, position), listener=_listener(s, who),
        rebuilt=bool(who) and L.is_rebuilt(_speaker_pack(who)),  # L1c stage 2 on by default for rebuilt characters
        voice_meta=L.voice_label_of(_speaker_pack(who)) if who else None,  # pack voice_label: records only, not TTS
        tts_backend=engine, ref=ref, target_s=float(getattr(s, "seconds", 0) or 0), scorer_ready=_scorer_ready())
    if quality == "final" and not s.lipsync:
        notes = ["Lip-sync is off for this shot: voice over the picture."]
    fallback = ""
    if want_sync and s.lipsync_backend == "latentsync" and mode != "ltx_a2v+latentsync":
        # LatentSync was picked but won't run: say why next to the take label, not only in More options
        fallback = next((n for n in notes if "LatentSync" in n or "Several faces" in n or "too small" in n), "")
    if not who and len(s.characters) > 1:
        notes.append("Nobody picked to say the line: the prompt doesn't name a speaker.")
    if voice_note:
        notes.append(voice_note)
    l1c = next((x for x in stages if x.get("only_if") == L.ONLY_IF_L1C_STAGE2), None)
    return {"line": s.line, "speaker": who, "voice": voice, "voice_from": voice_from, "mode": mode,
            "voice_engine": engine, "voice_ref": bool(ref), "voice_note": voice_note,
            "lipsync": bool(s.lipsync), "backend": s.lipsync_backend if mode != "tts_only" else None,
            "recipe": (l1c or {}).get("recipe"),
            "latentsync_est_s": (l1c or {}).get("cost_est_s"),  # L1c mouth pass GPU hint: ceil(frames/16) x 35.3 s
            "stage2_default_on": (l1c or {}).get("stage2_default_on"),
            "stage2_default_why": (l1c or {}).get("stage2_default_why"),
            **_voice_label_fields(who),
            "face_check": L.face_check(s.face_box, s.lipsync_backend, who), "notes": notes, "stages": stages,
            "best_of": next((x.get("best_of", 1) for x in stages if x.get("audio_from") == "voice"), 1),
            "seconds_est": stages[0]["seconds_est"], "fallback": fallback,
            "take_seconds_est": next((x["params"]["duration_s"] for x in stages
                                      if x.get("stage") == "video" and x.get("audio_from") == "voice"), None), "planned_seconds": float(getattr(s, "seconds", 0) or 0)}


def _best_of_record(res) -> dict | None:
    """The best-of-seeds result of the take (every seed's metrics and reject reasons), None when it had none."""
    return next(({k: v for k, v in x.items() if k != "stage"} for x in reversed(res.steps) if x.get("stage") == "best_of"),
                None)


def _lipsync_stats(res) -> dict | None:
    """The lip-sync runner's sidecar for the take's lipsync step (None when missing)."""
    from opensoul import lipsync as L

    f = next((x["file"] for x in reversed(res.steps) if x.get("stage") == "lipsync" and not x.get("error")), None)
    return L.read_sidecar(Path(f)) if f else None


def _tidy_note(n: str) -> str:
    """A take that already fell back to LTX audio+video doesn't need "Use LTX lip-sync" suggested again."""
    if "Kept LTX audio+video only" in n:
        n = n.replace(" Use LTX lip-sync or a closer shot.", "").replace(" Try a closer shot or LTX lip-sync.", "")
        n = n.replace("Kept LTX audio+video only.", "Kept LTX audio+video only (or move to a closer shot).")
    return n


MODE_LABEL = {"tts_only": "voice only", "ltx_a2v": "LTX audio+video lip-sync",
              "ltx_a2v+latentsync": "LTX audio+video + LatentSync"}


class SpeakIn(BaseModel):
    line: str | None = None    # default: the shot's saved line (lets the UI preview before saving)
    voice: str | None = None   # default: the shot's voice


@router.post("/projects/{pid}/shots/{sid}/speak")
def speak_line(pid: str, sid: str, req: SpeakIn):
    """Hear the line: the voice alone (no video). Dry run: a placeholder tone sized to the line."""
    from opensoul import lipsync as L

    st = _store()
    p = _err(st.load, pid)
    s = _err(p.shot, sid)
    d = _err(sb.clean_dialogue, {"line": req.line if req.line is not None else s.line,
                                 "voice": req.voice if req.voice is not None else s.voice})
    if not d["line"]:
        raise HTTPException(400, "Write what they say first.")
    voice = d["voice"] or _shot_voice(s)[0]
    engine, ref, voice_note = _voice_engine(_speaker(s), p.tts_engine)
    import hashlib

    # Orpheus keeps its old cache key, so lines already heard are not made again.
    tag = "" if engine == "orpheus" else f"|{engine}|{(ref or {}).get('sha256', '')}"
    key = hashlib.sha1(f"{voice}|{d['line']}|{_srv()._dry()}{tag}".encode()).hexdigest()[:12]
    dest = st.project_dir(pid) / "shots" / sid / "speak" / f"{key}.wav"
    try:
        wav, secs, ph = L.synth_line(d["line"], voice, dest, dry_run=_srv()._dry(), engine=engine, ref=ref)
    except Exception as e:  # noqa: BLE001  TTS server down / no ffmpeg: a plain message, not a 500
        raise HTTPException(503, f"Couldn't make the voice: {e}")
    return {"audio_url": _url(sb.rel_path(wav)), "seconds": round(secs, 2), "voice": voice,
            "speaker": _speaker(s), "line": d["line"], "placeholder": ph, "voice_engine": engine,
            "voice_note": voice_note}


def _music_shots(pid: str) -> dict:
    """{shot id: {song, sings, lyric, cut_s, render_s}} for the shots that came from Music hand-offs."""
    import json as _json

    try:
        folder = _store().project_dir(pid) / "music"
    except Exception:  # noqa: BLE001
        return {}
    out: dict = {}
    if not folder.is_dir():
        return out
    for f in sorted(folder.glob("*.json"), key=lambda x: x.stat().st_mtime):
        try:
            side = _json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for sid, row in (side.get("shots") or {}).items():
            c = (row or {}).get("cut") or {}
            out[sid] = {"song": side.get("title"), "sings": bool(c.get("lipsync")), "lyric": c.get("lyric") or "",
                        "cut_s": round(int(c.get("frames") or 0) / 24, 2),
                        "render_s": round(int(c.get("render_frames") or 0) / 24, 2)}
    return out


def _music_row(pid: str, sid: str) -> tuple[dict, dict] | None:
    """(side-car, row) of the newest Music hand-off that made this shot (data/projects/<id>/music/<song>.json)."""
    import json as _json

    folder = _store().project_dir(pid) / "music"
    if not folder.is_dir():
        return None
    for f in sorted(folder.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            side = _json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        row = (side.get("shots") or {}).get(sid)
        if isinstance(row, dict) and isinstance(row.get("cut"), dict):
            return side, row
    return None


def _music_plan(pid: str, s: sb.Shot, plan: dict, prompt: str, seed: int, quality: str, work: Path,
                size: tuple[int, int]) -> tuple[dict, dict | None]:
    """A shot made by Music > Make these shots (OS-023, OS-034, OS-043).

    * Every video take renders the cut's own length (render_frames, 8k+1), not the 7 s default.
    * A sung shot's Final with Lip-sync on renders with LTX audio+video from its slice of the song (the vocal stem
      when the studio has one, else the full mix): the song drives the mouth. No LatentSync.
    Returns (plan, info) where info is None for a shot that did not come from Music."""
    m = _music_row(pid, s.id)
    if m is None or s.line:
        return plan, None
    side, row = m
    cut = row["cut"]
    frames = int(cut.get("render_frames") or 0)
    info = {"song": side.get("title"), "frames": frames, "cut_s": round(int(cut.get("frames") or frames) / 24, 2),
            "sung": False}
    from opensoul import lipsync as L
    from opensoul.presets import NODE_AUDIO_LATENT, NODE_LATENT

    if cut.get("lipsync") and s.lipsync and quality == "final":
        audio = sb.abs_path(row.get("vocal_slice"))
        secs = frames / 24 if frames else float(cut.get("end_s", 0)) - float(cut.get("start_s", 0))
        if audio is None or not audio.is_file():
            song = sb.abs_path(side.get("song"))
            if song is not None and song.is_file():
                from opensoul.media import MediaError
                from opensoul.music import export as X

                try:
                    audio = X.slice_audio(song, float(cut.get("start_s", 0)), secs, work / "song_slice.wav")
                except (MediaError, OSError):
                    audio = None
        if audio is not None and Path(audio).is_file():
            who = side.get("character") or (s.characters[0] if s.characters else "")
            a2v = L.a2v_stage(prompt=L.speaker_prompt(prompt, who, cut.get("lyric") or ""), audio_s=secs, seed=seed,
                              width=1280 if size[0] > size[1] else 704, height=704 if size[0] > size[1] else 1280,
                              quality=quality)
            rest = [x for x in plan["stages"] if x["stage"] not in ("voice", "video", "lipsync")]
            plan = {**plan, "stages": [{"stage": "voice", "file": str(audio), "source": "song"}, a2v] + rest,
                    "notes": plan.get("notes", []) + [f"Sung to the song: LTX audio+video, {secs:.1f} s."]}
            info["sung"] = True
            return plan, info
    if frames:
        for x in plan["stages"]:
            if x.get("stage") == "video" and isinstance(x.get("inputs"), dict) and NODE_LATENT in x["inputs"]:
                x["inputs"][NODE_LATENT] = {**x["inputs"][NODE_LATENT], "length": frames}
                x["inputs"][NODE_AUDIO_LATENT] = {**(x["inputs"].get(NODE_AUDIO_LATENT) or {}), "frames_number": frames}
                x.setdefault("params", {}).update({"frames": frames, "duration_s": round(frames / 24, 2)})
        plan = {**plan, "notes": plan.get("notes", []) + [f"Renders {frames / 24:.1f} s for a {info['cut_s']:.1f} s cut."]}
    return plan, info


SILENT_HANDLE_S = 0.5   # OS-062: a picture-only Final renders its Length plus this, so the cut has room to trim
SILENT_MAX_S = 10.0     # longest picture-only Final (LTX drifts off the start frame in longer takes)


def _length_plan(plan: dict, s: sb.Shot, quality: str) -> dict:
    """OS-062: a picture-only Final with a Length renders that Length plus a short handle (8k+1 frames), not the
    workflow's 7.04 s. A Draft keeps its own short length; no Length keeps the default."""
    want = float(getattr(s, "seconds", 0) or 0)
    if quality != "final" or want <= 0:
        return plan
    from opensoul.camera_moves import frames_for
    from opensoul.presets import NODE_AUDIO_LATENT, NODE_LATENT

    secs = min(want + SILENT_HANDLE_S, SILENT_MAX_S)
    frames = frames_for(secs)
    hit = False
    for x in plan["stages"]:
        if x.get("stage") == "video" and isinstance(x.get("inputs"), dict):
            lat = x["inputs"].get(NODE_LATENT)
            if not isinstance(lat, dict):
                lat = x["inputs"][NODE_LATENT] = {}
            lat["length"] = frames
            x["inputs"][NODE_AUDIO_LATENT] = {**(x["inputs"].get(NODE_AUDIO_LATENT) or {}), "frames_number": frames}
            x.setdefault("params", {}).update({"frames": frames, "duration_s": round(frames / 24, 2)})
            hit = True
    if not hit:
        return plan
    note = f"Renders {frames / 24:.1f} s for a {want:g} s shot."
    if want + SILENT_HANDLE_S > SILENT_MAX_S:
        note += f" A picture-only take is {SILENT_MAX_S:g} s at most; the export holds the last frame."
    return {**plan, "notes": plan.get("notes", []) + [note]}


def _style_plan(plan: dict, look: str, shot_text: str, has_cast: bool = True, avoid: list[str] | None = None) -> dict:
    """Story-level look on a video plan (OS-006, OS-018, OS-038).

    * No Era post (grain, handheld shake) and no smartphone 'UGC' sentence: a story take is clean unless a look asks.
    * The look's style sentence leads every video prompt; the negative prompt drops the words that fight a drawn
      look ('cartoon', 'video game' ...) and drops 'closed eyes' / 'squinting' when the shot asks for a wink or a blink.
    * OS-039: the camera move is said in viewer words (no crane, jib or tripod), and the negative asks for no gear.
    """
    import json as _json

    from opensoul import camera_words as CW

    from opensoul import looks as LK
    from opensoul.presets import load_presets

    suffixes = [e.get("prompt_suffix", "") for e in load_presets()["eras"] if e.get("prompt_suffix")]
    stages = []
    for st_ in plan.get("stages", []):
        if st_.get("stage") == "era":
            continue
        if st_.get("stage") == "video" and isinstance(st_.get("inputs"), dict):
            st_ = {**st_, "inputs": dict(st_["inputs"])}
            inp = st_["inputs"]
            if isinstance(inp.get("20"), dict) and isinstance(inp["20"].get("text"), str):
                t = inp["20"]["text"]
                for suf in suffixes:
                    t = t.replace(suf, "")
                inp["20"] = {**inp["20"], "text": LK.video_prompt(CW.viewer_words(" ".join(t.split()), has_cast), look)}
            neg = (inp.get("21") or {}).get("text")
            if neg is None and st_.get("workflow"):
                try:
                    wf = _json.loads((sb.ROOT / st_["workflow"]).read_text(encoding="utf-8"))
                    neg = ((wf.get("21") or {}).get("inputs") or {}).get("text")
                except (OSError, ValueError, AttributeError):
                    neg = None
            if isinstance(neg, str):
                text = CW.negative(LK.negative(neg, look, shot_text))
                if avoid:  # OS-068: the story's Avoid list
                    from opensoul.originality import negative as _avoid_neg

                    text = _avoid_neg(text, avoid)
                inp["21"] = {**(inp.get("21") or {}), "text": text}
        stages.append(st_)
    prompt = plan.get("prompt", "")
    for suf in suffixes:
        prompt = prompt.replace(suf, "")
    return {**plan, "stages": stages, "era": None,
            "prompt": LK.video_prompt(CW.viewer_words(" ".join(prompt.split()), has_cast), look)}


def _render_times(res) -> dict:
    """OS-041: the take card shows the studio's render time; time in the studio queue is kept apart."""
    vids = [x for x in (res.steps or []) if x.get("stage") == "video"]
    if vids and all("run_s" in x for x in vids):
        run = sum(float(x["run_s"]) for x in vids)
        queue = sum(float(x.get("queue_s") or 0) for x in vids)
        other = max(0.0, float(res.seconds or 0) - sum(float(x.get("secs") or 0) for x in vids))  # voice, post ...
        return {"render_seconds": round(run + other, 1), "queue_seconds": round(queue, 1), "wall_seconds": res.seconds}
    return {"render_seconds": res.seconds}


def _frame_times(t0: float) -> dict:
    import time

    wall = round(time.time() - t0, 1)
    try:
        from opensoul.comfy_client import last_timing

        t = last_timing()
    except Exception:  # noqa: BLE001
        t = {}
    if t and t.get("run_s") is not None and t["run_s"] <= wall + 1:
        return {"render_seconds": t["run_s"], "queue_seconds": t.get("queue_s", 0), "wall_seconds": wall}
    return {"render_seconds": wall}


def _dropped_note(s: sb.Shot, edit: str) -> str:
    used, mouth = _talk_edit(s, edit)
    _, dropped = _merge_edit(s.prompt or "", used)
    notes = []
    if mouth:  # OS-060
        notes.append("On a talking shot the voice moves the mouth, so these words of your change were not used: "
                     + "; ".join(f"“{d}”" for d in mouth[:3]) + ".")
    if dropped:
        notes.append("Your change won over these words of What happens: " + "; ".join(f"“{d}”" for d in dropped[:3])
                     + ". Change What happens to keep it that way.")
    return " ".join(notes)


def _keeper_is_still(s: sb.Shot) -> bool:
    """OS-058: True when the shot's keeper is a still (a start frame or a concept image), or there is no keeper. The
    first video take that is ready then becomes the keeper (the rule of OS-026); a video keeper never changes."""
    k = s.keeper_version()
    return k is None or k.kind in ("frame", "concept", "card") or (k.kind == "upload" and _is_still(k.file))


def _make_take(pid: str, p: sb.Project, s: sb.Shot, *, prompt: str, edit: str, seed: int, base: Path | None,
               based_on: str | None, quality: str, keep_when_ready: bool = False,
               extra_notes: list[str] | None = None) -> dict:
    srv = _srv()
    st = _store()
    sid = s.id
    take = _err(st.reserve_take, pid, sid)
    work = st.take_dir(pid, sid, take)
    qlabel = QUALITY_LABEL[quality]
    settings = {"camera": s.camera, "aspect": p.aspect, "base_image": sb.rel_path(base) if base else None,
                "quality": quality}
    stretched = ""
    if s.camera_moves:
        from opensoul import camera_moves as cm

        try:
            cm.check_quality(s.camera_moves, quality)
        except cm.MoveError as e:
            raise HTTPException(400, str(e))
        settings["camera_moves"] = list(s.camera_moves)
        settings["camera_prompt"] = cm.stack_prompt(s.camera_moves)  # what the video prompt gets (prompt-only)
        need = cm.min_seconds(s.camera_moves)
        if quality == "draft" and need:  # a Draft is 4 s at most, so a 2-move stack is always lengthened
            stretched = f"Lengthened to {need:g} s for {len(s.camera_moves)} moves."
            settings["min_seconds"] = need
    size = sb._size(p.aspect)
    if srv._dry():
        from opensoul import preview_samples

        # Preview mode can't render: the take is a labelled sample clip from a real OpenSoul render (P0-01), so the
        # Review cards and the export show real pictures. No sample files or no ffmpeg: the old stand-in card.
        index = next((i for i, x in enumerate(p.shots) if x.id == s.id), 0)
        sample = preview_samples.make_take(index + take - 1, work, size)
        if sample:
            clip, poster, smp = sample
            cfg = preview_samples.load()
            label = f"{cfg.get('label') or 'Preview sample from a real render'} ({qlabel})"
            note = cfg.get("note") or "Preview mode shows a sample clip. Studio mode renders your own take."
            settings["sample"] = {"video": smp["video"], "credit": cfg.get("credit") or "", "cast": cfg.get("cast") or ""}
        else:
            who = ", ".join(s.characters) or p.character or s.beat
            poster = _stamp(base, work / "poster.jpg", who, take, edit, size)
            clip = None
            try:
                from opensoul import media

                clip = media.still_to_clip(poster, work / "preview.mp4", seconds=2.0, width=size[0], height=size[1])
            except Exception:  # noqa: BLE001  no ffmpeg: the still is the take
                clip = None
            label, note = f"Preview take ({qlabel}) · stand-in", "Preview mode: a stand-in. Studio mode renders the real take."
        dia = _dialogue(s, prompt=prompt, quality=quality, seed=seed, size=size, position=_position(p, s),
                        project_engine=p.tts_engine)
        if stretched:
            note = f"{note} {stretched}"
            settings["length_note"] = stretched
        if dia:
            from opensoul import lipsync as L

            settings["dialogue"] = {k: v for k, v in dia.items() if k != "stages"}
            settings["job"] = {"stages": dia["stages"]}
            try:
                secs = dia["seconds_est"]
                wav = L.placeholder_voice(work / "voice.wav", secs)
                if dia["mode"] != "tts_only":
                    a2v = next((x for x in dia["stages"] if x.get("stage") == "video" and x.get("audio_from")), {})
                    wav = L.pad_audio(wav, work / "voice_padded.wav",
                                      float(a2v.get("pad_audio_to_s") or L.padded_seconds(secs)))
                if clip:
                    clip = L.mux_voice(clip, wav, work / "take.mp4")
            except Exception:  # noqa: BLE001  no ffmpeg: the silent stand-in stays the take
                pass
            label = f"{label} · {MODE_LABEL[dia['mode']]}"
            note = note + " " + " ".join(dia["notes"])
        note = " ".join([note.strip(), *(extra_notes or [])])
        _err(st.add_version, pid, sid, take=take, file=sb.rel_path(clip or poster), poster=sb.rel_path(poster),
             prompt=prompt, edit=edit, seed=seed, settings=settings, kind="preview", placeholder=True,
             label=label, note=note.strip(), based_on=based_on,
             keep=keep_when_ready or _keeper_is_still(s))  # same rule as a real take (OS-026, OS-058)
        return _project_json(st.load(pid))
    if base is None:
        who = (s.characters or [p.character or "This shot"])[0]
        raise HTTPException(400, f"{who} has no picture yet. Make a start frame or a character sheet first.")
    from opensoul.presets import build_shot_plan

    try:
        talker = _speaker(s) if (s.line or s.speaker) else ""
        plan = build_shot_plan(camera=s.camera, camera_moves=s.camera_moves or None, character_prompt=prompt, seed=seed, quality=quality,
                               speaker=talker, pronoun=_speaker_pronoun(talker) if talker else None,
                               speaks=bool(s.line or s.speaker),
                               overrides={"width": 1280 if size[0] > size[1] else 704,
                                          "height": 704 if size[0] > size[1] else 1280})
    except KeyError as e:
        raise HTTPException(400, f"Unknown camera move {e}.")
    except ValueError as e:  # camera_moves.MoveError: a clash, said plainly
        raise HTTPException(400, str(e))
    vid = next((x for x in plan["stages"] if x["stage"] == "video"), None)
    dia = _dialogue(s, prompt=prompt, quality=quality, seed=seed, size=size, i2v_stage=vid,
                    position=_position(p, s), project_engine=p.tts_engine)
    if dia:  # the line's stages (voice, video or a2v video, mux / lipsync) replace the plan's; Era etc. stay after
        rest = [x for x in plan["stages"] if x["stage"] not in ("voice", "video", "lipsync")]
        plan = {**plan, "stages": dia["stages"] + rest, "notes": plan.get("notes", []) + dia["notes"]}
        settings["dialogue"] = {k: v for k, v in dia.items() if k != "stages"}
        settings["job"] = {"stages": dia["stages"]}
    if extra_notes:
        plan = {**plan, "notes": plan.get("notes", []) + list(extra_notes)}
    plan, music = _music_plan(pid, s, plan, prompt, seed, quality, work, size)
    if music:
        settings["music"] = music
    elif not dia:
        plan = _length_plan(plan, s, quality)  # OS-062: a picture-only Final is the shot's Length, not always 7 s
    from opensoul import originality as OG

    plan = _style_plan(plan, p.look, f"{s.prompt} {edit}", has_cast=bool(s.characters), avoid=OG.for_project(p))
    settings["look"] = p.look or "photo"
    if s.camera_moves:  # the line's own stages too: 2 moves >= 5 s, 3 moves >= 7 s
        from opensoul import camera_moves as cm

        for x in plan["stages"]:
            n = cm.stretch_video(x, s.camera_moves)
            if n and n not in plan.get("notes", []):
                plan = {**plan, "notes": plan.get("notes", []) + [n]}
        stretched = next((n for n in plan.get("notes", []) if n.startswith("Lengthened to")), "")
    _err(st.add_version, pid, sid, take=take, prompt=prompt, edit=edit, seed=seed,
         settings={**settings, "plan_notes": plan.get("notes", []), **({"length_note": stretched} if stretched else {})},
         kind="render", status="rendering",
         label=f"Rendering {qlabel.lower()}{' · ' + MODE_LABEL[dia['mode']] if dia else ''}"
               f"{' · sung to the song' if music and music.get('sung') else ''}…", based_on=based_on)

    def run() -> None:
        from opensoul.shot import run_shot

        try:
            res = run_shot(plan, base, work, max_reseeds=2 if p.fix_camera else None)
            poster = work / "poster.jpg"
            try:
                import subprocess

                from opensoul.media import ffmpeg_bin

                subprocess.run([ffmpeg_bin() or "ffmpeg", "-y", "-loglevel", "error", "-i", str(res.video),
                                "-frames:v", "1", str(poster)], check=False, capture_output=True)
            except Exception:  # noqa: BLE001
                pass
            if dia and any(x.get("stage") == "lipsync" and x.get("error") == "no_face" for x in res.steps):
                from opensoul import lipsync as L

                settings["dialogue"] = {**settings["dialogue"], "mode": "ltx_a2v",
                                        "fallback": L.no_face_note(settings["dialogue"].get("speaker", ""))}
            st.update_version(pid, sid, f"v{take}", file=sb.rel_path(res.video),
                              poster=sb.rel_path(poster) if poster.is_file() else None, status="ready",
                              label=qlabel + (" · sung to the song" if music and music.get("sung") else ""),
                              note="; ".join(_tidy_note(n) for n in res.notes),
                              settings={**settings, "steps": res.steps, **_render_times(res),
                                        **({"lipsync_stats": _lipsync_stats(res)} if dia else {}),
                                        **({"lipsync_best_of": bo} if (bo := _best_of_record(res)) else {})})
            if keep_when_ready or _keeper_is_still(st.load(pid).shot(sid)):  # OS-058: a video wins over a still
                st.set_keeper(pid, sid, f"v{take}")
        except Exception as e:  # noqa: BLE001  keep the failed take visible with the reason
            note = f"Couldn't render: {e}"
            try:  # OS-055: a Kokoro voice file the studio doesn't have is not offered again
                from opensoul import studio_info

                gone = studio_info.note_missing_voice(srv.DATA, str(e))
                if gone:
                    note += f" The studio has no voice file {gone}. OpenSoul stops offering that voice here."
            except Exception:  # noqa: BLE001
                pass
            st.update_version(pid, sid, f"v{take}", status="failed", label="Failed", note=note)

    srv._start(run)
    return _project_json(st.load(pid))


# ---------------------------------------------------------------- cast + start frames
# Demo mode (OPENSOUL_DEMO_CAST=1: the judge demo and screenshot servers): the cast shows only these example
# characters plus what was made since this server started, so test characters left in a data folder never appear.
DEMO_CAST_ALLOW = ("juno pell", "lumi", "mio", "ren", "pixel")  # Juno Pell: the Preview demo cast


def demo_cast_mode() -> bool:
    return os.environ.get("OPENSOUL_DEMO_CAST", "") == "1"


def _demo_hidden(name: str, pack_json: Path) -> bool:
    if not demo_cast_mode() or name.lower() in DEMO_CAST_ALLOW:
        return False
    from datetime import datetime

    started = datetime.fromisoformat(_srv()._START["started"]).timestamp()
    return pack_json.stat().st_mtime < started


def _pack_cast() -> list[dict]:
    """Characters the user saved in the app (DATA/packs/<name>/pack.json), newest first. Never the demo."""
    from opensoul.character_pack import CharacterPack

    srv = _srv()
    root = srv.DATA / "packs"
    out = []
    dirs = sorted((d for d in root.glob("*") if (d / "pack.json").is_file()), key=lambda d: (d / "pack.json").stat().st_mtime,
                  reverse=True) if root.is_dir() else []
    for d in dirs:
        try:
            if srv._is_demo_pack(d) or srv._pack_borrows_demo(d):
                continue
            pack = CharacterPack.load(d)
        except (ValueError, TypeError, OSError):
            continue
        name = " ".join(str(pack.name or "").split())
        if not name or _demo_hidden(name, d / "pack.json"):
            continue
        refs = srv._own_refs(d)
        base = srv._pack_folder(name)
        m = re.fullmatch(re.escape(base) + r"_(\d+)", d.name)
        origin = ((pack.meta or {}).get("origin") or {}).get("kind") or ""
        try:  # optional voice_label (lip-sync metadata, shown read only; the TTS voice is character_voices)
            from opensoul.lipsync import VOICE_LABEL_KEY, voice_label_of

            vlabel = voice_label_of(json.loads((d / "pack.json").read_text(encoding="utf-8"))).get(VOICE_LABEL_KEY)
        except (OSError, ValueError, TypeError, KeyError):
            vlabel = None
        out.append({"name": name, "prompt_lock": pack.prompt_lock or "", "picture": refs[0] if refs else None,
                    "origin": origin, "sheet": srv._pack_sheet(d), "look_pending": "", "source": "app", "pack_dir": str(d),
                    "folder": d.name, "variant": int(m.group(1)) if m else (1 if d.name == base else None),
                    "voice_label": vlabel})
    return out


def _resolve_pack(name: str, packs: list[dict] | None = None) -> dict | None:
    """Which of the user's packs a character *name* means when several share it (Lumi, Lumi_2, Lumi_4 ...).

    The original folder (<name>, variant 1) wins; then the lowest numbered <name>_N; a pack in a differently named
    folder last (newest first). A newer _N never shadows the original: it is listed as a variant instead."""
    same = [c for c in (packs if packs is not None else _pack_cast()) if c["name"].lower() == name.lower()]
    if not same:
        return None
    return min(same, key=lambda c: (c.get("variant") is None, c.get("variant") or 0))


def _variants(name: str, chosen: str | None, packs: list[dict], chosen_picture=None) -> list[dict]:
    """The other packs saved under the same name (shown, never merged). A pack whose picture is byte-identical to the
    one in use (or to a version already listed) is the same version saved twice, so it isn't counted again."""
    srv = _srv()
    same_name = [c for c in packs if c["name"].lower() == name.lower()]
    chosen_pack = next((c for c in same_name if c["pack_dir"] == chosen), None)
    seen = set()
    for pic in (chosen_picture, (chosen_pack or {}).get("picture")):
        if pic and Path(pic).is_file():
            seen.add(srv._md5(Path(pic)))
    out = []
    for c in sorted((c for c in same_name if c["pack_dir"] != chosen), key=lambda c: (c.get("variant") is None, c.get("variant") or 0)):
        pic = c.get("picture")
        h = srv._md5(Path(pic)) if pic and Path(pic).is_file() else None
        if h and h in seen:
            continue
        if h:
            seen.add(h)
        out.append({"folder": c.get("folder") or Path(c["pack_dir"]).name, "variant": c.get("variant"), "pack_dir": c["pack_dir"],
                    "picture": pic})
    return out


def _cast_library() -> list[dict]:
    """Everyone a story can cast: the user's own characters. Saved library folders (assets/<slug>/character.json)
    first, then characters made in the app (data/packs). One entry per name; never the demo character."""
    import json

    srv = _srv()
    out, seen = [], set()
    packs = _pack_cast()
    for cj in sorted(srv.LIBRARY.glob("*/character.json")):
        try:
            meta = json.loads(cj.read_text(encoding="utf-8"))
        except ValueError:
            continue
        name = meta.get("name", "")
        lib = srv._library(name) if name else None
        # A saved character whose pictures aren't in this copy (a release leaves the pre-rebuild art out) still shows,
        # with a text placeholder card; shots treat it as "no picture yet".
        if lib and lib["name"].lower() not in seen:
            seen.add(lib["name"].lower())
            out.append({"name": lib["name"], "prompt_lock": lib.get("prompt_lock", ""), "picture": lib["reference"],
                        "sheet": lib.get("sheet"), "look_pending": str(meta.get("look_pending") or ""), "source": "library",
                        "variants": _variants(lib["name"], None, packs, lib["reference"]),
                        # the pack a talk take reads (_speaker_pack) carries the optional voice_label
                        "voice_label": (_resolve_pack(lib["name"], packs) or {}).get("voice_label")})
    for c in packs:
        if c["name"].lower() not in seen:
            seen.add(c["name"].lower())
            best = _resolve_pack(c["name"], packs)
            out.append({**best, "variants": _variants(c["name"], best["pack_dir"], packs)})
    return out


def srv_slug(name: str) -> str:
    return _srv()._ascii_slug(name, "")


def _cast_json(c: dict) -> dict:
    from opensoul.character_voices import voice_for

    return {"name": c["name"], "prompt_lock": c["prompt_lock"], "voice": voice_for(_srv().DATA, c["name"]),
            "picture_url": _url(sb.rel_path(c["picture"])) if c.get("picture") else None,
            "sheet_url": _url(sb.rel_path(c["sheet"])) if c.get("sheet") else None,
            "look_pending": c.get("look_pending", ""), "source": c.get("source", "library"),
            "voice_label": c.get("voice_label"),  # lip-sync metadata from the pack, read only (TTS uses "voice")
            "made_from_text": c.get("origin") == "text",
            "folder": c.get("folder") or ("assets/" + srv_slug(c["name"]) if c.get("source") == "library" else None),
            "variants": [{"folder": v["folder"], "variant": v["variant"],
                          "picture_url": _url(sb.rel_path(v["picture"])) if v.get("picture") else None}
                         for v in c.get("variants") or []],
            **_card(c["name"])}


def _card(name: str) -> dict:
    """The picture shown on this character's card (display only; renders use the pack): presets/demo_images.json."""
    from opensoul.demo_images import cast_card

    return cast_card(name)


@router.get("/cast")
def cast():
    return {"cast": [_cast_json(c) for c in _cast_library()]}


class VoiceIn(BaseModel):
    voice: str


@router.put("/cast/{name}/voice")
def set_cast_voice(name: str, body: VoiceIn):
    """Pick a character's voice (a built-in Orpheus voice). Used for every line they speak."""
    from opensoul.character_voices import set_voice

    name = " ".join(str(name or "").split())
    c = next((x for x in _cast_library() if x["name"].lower() == name.lower()), None)
    if c is None:
        raise HTTPException(404, f"{name or 'That character'} isn't in your characters.")
    try:
        v = set_voice(_srv().DATA, c["name"], body.voice)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"name": c["name"], "voice": v}


@router.put("/cast/{name}/voice-clip")
async def set_cast_voice_clip(name: str, clip: UploadFile = File(...), consent: bool = Form(False),
                              made_with: str = Form(""), ref_text: str = Form("")):
    """Give a character their own reference clip (5-15 s WAV) for the cloning voice engines (Chatterbox, VoxCPM2).

    Saved as voice/ref.wav in the character's folder with its sha256, provenance and consent; never used without
    consent. Orpheus stories don't use it, so nothing changes for them."""
    import io
    import wave

    from opensoul import voice_engine as VE

    name = " ".join(str(name or "").split())
    c = _resolve_pack(name) if name else None
    if c is None:
        raise HTTPException(404, f"{name or 'That character'} has no saved folder to keep a voice clip in.")
    if not consent:
        raise HTTPException(400, "Tick the consent box: " + VE.CONSENT_TEXT)
    made_with = " ".join(str(made_with or "").split())[:200]
    if not made_with:
        raise HTTPException(400, "Say how you made the clip (for example: my own recording, or a voice-design model).")
    data = await clip.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "That clip is too big. Use a 5-15 second WAV.")
    try:
        with wave.open(io.BytesIO(data)) as w:
            secs = w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, ZeroDivisionError):
        raise HTTPException(400, "That isn't a WAV file. Use a 5-15 second WAV.")
    if not 5.0 <= secs <= 15.0:
        raise HTTPException(400, f"The clip is {secs:.1f} s. Use 5-15 seconds of clean speech.")
    pack_dir = Path(c["pack_dir"])
    dest = pack_dir / "voice" / "ref.wav"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    pj = pack_dir / "pack.json"
    try:
        pack = json.loads(pj.read_text(encoding="utf-8")) if pj.is_file() else {}
    except (OSError, ValueError):
        raise HTTPException(500, "Couldn't read this character's pack.json, so OpenSoul did not link the clip.")
    from opensoul.character_voices import voice_for

    old = pack.get("voice") if isinstance(pack.get("voice"), dict) else {}
    pack["voice"] = {**old, "orpheus_voice": old.get("orpheus_voice") or voice_for(_srv().DATA, c["name"]),
                     "ref_clip": "voice/ref.wav", "ref_text": " ".join(str(ref_text or "").split())[:500],
                     "ref_sha256": VE.sha256(dest), "ref_made_with": made_with, "consent": True,
                     "consent_text": VE.CONSENT_TEXT}
    sb.atomic_write_json(pj, pack)
    return {"name": c["name"], "seconds": round(secs, 2), "ref_sha256": pack["voice"]["ref_sha256"],
            "engine": VE.voice_block(pack)["engine"]}


async def save_character(*, name: str, description: str = "", uploads: list | None = None, consent: bool = False,
                         kind: str = "reference", replace: bool = False, seed: int = 42, use_library: bool = True,
                         require_consent: bool = True) -> tuple[Path, dict | None]:
    """The one way a character is saved (Create, the Storyboard and POST /api/cast all come here).

    replace=False (the cast): a new character; a name that's taken is refused, a pack folder that exists gets _N.
    replace=True (Create's "Save"): the character's own folder DATA/packs/<Name> is written again, and with no picture a
    saved library character keeps its real reference. Up to three pictures; each is checked to be an image and never a
    demo character's picture. Returns (pack folder, cast entry or None). Nothing is rendered here."""
    srv = _srv()
    if replace:
        name = srv._clean_name(name)
    else:
        name = " ".join(str(name or "").split())[:60]
        if not name:
            raise HTTPException(400, "Give the character a name.")
        if any(c["name"].lower() == name.lower() for c in _cast_library()):
            raise HTTPException(400, f"{name} is already in your characters.")
    description = " ".join(str(description or "").split())[:1000]
    ups = [u for u in (uploads or []) if u is not None and getattr(u, "filename", "")][:3]
    if ups and require_consent and not consent:
        raise HTTPException(400, "Please confirm you own this picture or have permission to use it.")
    up = srv.DATA / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    import uuid

    from PIL import Image

    for u in ups:
        data = await u.read()
        if not data:
            if replace:
                continue
            raise HTTPException(400, "That file is empty. Pick a picture and try again.")
        src = up / f"cast_{uuid.uuid4().hex[:8]}{Path(u.filename).suffix.lower() or '.png'}"
        src.write_bytes(data)
        try:
            Image.open(src).verify()
        except Exception:  # noqa: BLE001
            src.unlink(missing_ok=True)
            raise HTTPException(400, "That file isn't an image we can read. Try a JPG or PNG.")
        if srv._is_demo_image(src, name):
            src.unlink(missing_ok=True)
            raise HTTPException(400, "That's a picture of the demo character. Use your own character's picture.")
        saved.append(src)
    from opensoul.pipeline import build_character_pack

    if replace:
        lib = srv._library(name) if not saved and use_library else None
        if lib and lib["reference"]:
            saved = [lib["reference"]]  # a saved character: keep its real reference picture
            description = description or lib["prompt_lock"]
        if not saved and not description:
            raise HTTPException(400, "Add a short description (or a photo) so we know who this is.")
        folder = srv.DATA / "packs" / srv._pack_folder(name)
    else:
        if not saved and len(description) < 8:
            raise HTTPException(400, "Add a picture (a reference or a character sheet), or describe them in a few words.")
        folder = srv.DATA / "packs" / srv._pack_folder(name)
        base, i = folder, 2
        while folder.exists():
            folder, i = base.with_name(f"{base.name}_{i}"), i + 1
    (srv.DATA / "packs").mkdir(parents=True, exist_ok=True)
    build_character_pack(name, saved, description, folder, seed=seed)
    from opensoul.character_voices import ensure_voice

    from opensoul.voice_engine import available_voice_ids

    # a new character gets a voice nobody else uses (never Lumi's by accident), of their gender (OS-048)
    ensure_voice(srv.DATA, name, text=description or "", available=available_voice_ids(srv.DATA))
    if saved and kind == "sheet":
        import shutil

        shutil.copy2(saved[0], folder / f"character_sheet{saved[0].suffix.lower() if saved[0].suffix.lower() in ('.jpg', '.png') else '.jpg'}")
    c = next((x for x in _cast_library() if x["name"].lower() == name.lower()), None)
    return folder, c


@router.post("/cast")
async def new_cast_member(
    name: str = Form(""),
    description: str = Form(""),
    kind: str = Form("reference"),      # "reference" (one picture of them) | "sheet" (a character sheet image)
    consent: bool = Form(False),
    image: UploadFile | None = File(default=None),
    images: list[UploadFile] = File(default=[]),
):
    """Add a character to the user's library: a reference picture (up to three) or a sheet, or a description.
    Also served as POST /api/cast (the one cast API); only an uploaded picture needs the consent tick."""
    _folder, c = await save_character(name=name, description=description, uploads=[image, *images], consent=consent, kind=kind)
    name = c["name"] if c else " ".join(str(name or "").split())[:60]
    return {"character": _cast_json(c) if c else {"name": name}, "cast": [_cast_json(x) for x in _cast_library()]}


def _shot_cast(s: sb.Shot, pictures_only: bool = True) -> tuple[list[dict], list[str]]:
    """(cast members [with pictures], names not usable yet) for a shot, in the shot's order."""
    lib = {c["name"].lower(): c for c in _cast_library()}
    found, missing = [], []
    for n in s.characters:
        c = lib.get(" ".join(str(n).split()).lower())
        (found.append(c) if c and (c.get("picture") or not pictures_only) else missing.append(n))
    return found, missing


class FrameIn(BaseModel):
    edit: str = ""
    seed: int | None = None


@router.post("/projects/{pid}/shots/{sid}/frame")
def make_frame(pid: str, sid: str, req: FrameIn):
    """New start-frame take (a still): the shot's cast, from their saved pictures, composed into the shot's scene."""
    from opensoul import scene

    srv = _srv()
    st = _store()
    p = _err(st.load, pid)
    s = _err(p.shot, sid)
    _not_a_card(s)
    cast_, missing = _shot_cast(s)
    loc = p.location(s.location)
    plate_rel = loc.plate_for(s.stage_angle) if loc else ""
    angle = loc.angle(s.stage_angle) if loc else None
    plate = sb.abs_path(plate_rel) if plate_rel else None
    if plate is not None and not plate.is_file():
        plate = None
    room = scene.MAX_CAST - (1 if plate else 0)
    words_only = not cast_ and not plate and not missing  # OS-066: no cast, no stage: a frame from the words alone
    if not cast_ and not plate and missing:
        raise HTTPException(400, "This shot has no cast member with a picture and no stage. Make a character sheet, or pick a stage.")
    if words_only and not _shot_prompt(p, s).strip() and not (req.edit or "").strip():
        raise HTTPException(400, "Describe the shot in What happens first. OpenSoul makes the frame from those words.")
    if len(cast_) > room:
        raise HTTPException(400, f"A start frame fits up to {room} characters with pictures"
                            + (" next to the location plate." if plate else "."))
    import random

    edit = (req.edit or "").strip()[:500]
    seed = req.seed if req.seed is not None else random.randint(1, 2**31 - 2)
    text, dropped = _merge_edit(_shot_prompt(p, s), edit)  # OS-037: the change goes last and wins
    if missing:
        text += " Also in the scene: " + ", ".join(missing) + "."
    from opensoul import looks as LK

    if words_only:
        prompt = scene.text_prompt(text, style=LK.prompt(scene.STYLE, p.look))
    else:
        prompt = scene.cast_prompt(cast_, text, style=LK.prompt(scene.STYLE, p.look), location={"name": loc.name, "description": loc.description,
                                                                 "angle": angle.name if angle and angle.image else "",
                                                                 "angle_note": angle.note if angle and angle.image else ""}
                                    if plate else None)
        if plate and not cast_ and not missing and scene.NO_PEOPLE not in prompt:
            prompt += " " + scene.NO_PEOPLE  # OS-066: a stage shot with no cast shows the place, not a stray person
    from opensoul import originality as OG

    avoid = OG.for_project(p)
    guard = OG.sentence(avoid, f"{s.prompt} {edit}", defaults=p.avoid_defaults)
    if guard:  # OS-068: cfg-1 models read the picture prompt, not a negative prompt
        prompt += " " + guard
    ip_note = OG.note(f"{s.prompt} {edit}")
    take = _err(st.reserve_take, pid, sid)
    dest = st.take_dir(pid, sid, take) / "frame.png"
    pics = ([str(plate)] if plate else []) + [c["picture"] for c in cast_]
    settings = {"cast": [c["name"] for c in cast_], "workflow": "workflows/07z_master_from_text_zimage_api.json"
                if words_only else "workflows/08_scene_compose_api.json",
                "aspect": p.aspect, "pictures": [sb.rel_path(x) for x in pics]}
    if words_only:
        settings["from_words"] = True
    if avoid:
        settings["avoid"] = avoid
    if plate:
        settings["location"] = loc.name
        if angle and angle.image:
            settings["stage_angle"] = angle.name
    names = " + ".join([c["name"] for c in cast_] + ([loc.name] if plate else [])) or "From the words"
    if srv._dry():
        scene.preview_frame(pics, dest, aspect=p.aspect, label=f"{names} · {s.beat}")
        _err(st.add_version, pid, sid, take=take, file=sb.rel_path(dest), poster=sb.rel_path(dest), prompt=prompt,
             edit=edit, seed=seed, settings=settings, kind="frame", placeholder=True,
             label="Start frame · placeholder",
             note=" ".join(x for x in ("Preview mode: a stand-in. Studio mode renders the real frame.", ip_note) if x))
        return _project_json(st.load(pid))
    _err(st.add_version, pid, sid, take=take, prompt=prompt, edit=edit, seed=seed, settings=settings, kind="frame",
         status="rendering", label="Composing start frame…")

    def run() -> None:
        import time

        t0 = time.time()
        try:
            if words_only:
                from opensoul import originality as _og

                scene.text_frame(prompt, seed, dest, aspect=p.aspect,
                                 negative=_og.negative("text, watermark, logo", avoid))
            else:
                scene.compose_frame(pics, prompt, seed, dest, aspect=p.aspect, avoid=avoid)
            if plate and cast_:  # plate lock: the set comes pixel-for-pixel from the master plate. With no cast it
                # would return the plate unchanged (OS-066), so a cast-free stage shot keeps the model's picture.
                _plate_lock_still(dest, plate)
                settings["plate_lock"] = True
            frame_note = " ".join(x for x in (_dropped_note(s, edit) if dropped else "", ip_note) if x)
            st.update_version(pid, sid, f"v{take}", file=sb.rel_path(dest), poster=sb.rel_path(dest), status="ready",
                              label="Start frame", settings={**settings, **_frame_times(t0)},
                              **({"note": frame_note} if frame_note else {}))
        except Exception as e:  # noqa: BLE001
            st.update_version(pid, sid, f"v{take}", status="failed", label="Failed", note=f"Couldn't compose: {e}")

    srv._start(run)
    return _project_json(st.load(pid))


def _plate_lock_still(dest, plate) -> None:
    """Copy the location plate back over everything in `dest` that isn't an actor or prop.
    The unlocked render is kept next to it as frame_raw.png."""
    import cv2

    from opensoul.plate_lock import lock_frame

    frame, pl = cv2.imread(str(dest)), cv2.imread(str(plate))
    if frame is None or pl is None:
        return
    raw = dest.with_name("frame_raw.png")
    cv2.imwrite(str(raw), frame)
    locked, _ = lock_frame(frame, pl)
    cv2.imwrite(str(dest), locked)


def _not_a_card(s: sb.Shot) -> None:
    if getattr(s, "kind", "scene") == "card":
        raise HTTPException(400, "This shot is a title card. Click Make the card. A card needs no model.")


@router.post("/projects/{pid}/shots/{sid}/card")
def make_card(pid: str, sid: str):
    """OS-063: draw the shot's title or end card on this computer (Pillow, no model, no GPU) as a new still take.
    The words are exactly the card's words. It becomes the keeper when the keeper is a still or there is none."""
    from opensoul import cards

    st = _store()
    p = _err(st.load, pid)
    s = _err(p.shot, sid)
    if s.kind != "card":
        raise HTTPException(400, "This shot is not a card. Set its type to Card first.")
    take = _err(st.reserve_take, pid, sid)
    dest = st.take_dir(pid, sid, take) / "card.png"
    try:
        cards.render(s.card_title, s.card_sub, s.card_bg, dest, aspect=p.aspect)
    except cards.CardError as e:
        raise HTTPException(400, str(e))
    _err(st.add_version, pid, sid, take=take, file=sb.rel_path(dest), poster=sb.rel_path(dest), kind="card",
         label="Card", prompt=" / ".join(x for x in (s.card_title, s.card_sub) if x), keep=_keeper_is_still(s),
         settings={"card": {"title": s.card_title, "sub": s.card_sub, "bg": s.card_bg}, "aspect": p.aspect,
                   "source": "drawn on this computer (Pillow)"})
    return _project_json(st.load(pid))


UPLOAD_STILL = {".png", ".jpg", ".jpeg", ".webp"}
UPLOAD_VIDEO = {".mp4", ".mov", ".webm", ".m4v"}
UPLOAD_MAX = 400 * 1024 * 1024


@router.post("/projects/{pid}/shots/{sid}/upload")
async def upload_take(pid: str, sid: str, consent: bool = Form(False), file: UploadFile | None = File(default=None)):
    """OS-064: add your own still or clip to a shot as a new take (label 'Uploaded'). It can be the keeper and goes
    into the export like any take. It is never sent to a model."""
    st = _store()
    p = _err(st.load, pid)
    s = _err(p.shot, sid)
    if file is None or not file.filename:
        raise HTTPException(400, "Choose a picture or a video clip.")
    ext = Path(file.filename).suffix.lower()
    if ext not in UPLOAD_STILL | UPLOAD_VIDEO:
        raise HTTPException(400, "Use a PNG, JPG or WebP picture, or an MP4, MOV or WebM clip.")
    if not consent:
        raise HTTPException(400, "Please confirm you made this file or have permission to use it.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "That file is empty. Pick another file.")
    if len(data) > UPLOAD_MAX:
        raise HTTPException(400, "That file is too big. Use a file under 400 MB.")
    take = _err(st.reserve_take, pid, sid)
    work = st.take_dir(pid, sid, take)
    work.mkdir(parents=True, exist_ok=True)
    dest = work / f"upload{ext}"
    dest.write_bytes(data)
    poster = dest
    if ext in UPLOAD_STILL:
        try:
            _need_picture(dest, "picture")
        except HTTPException:
            dest.unlink(missing_ok=True)
            raise
    else:
        from opensoul import media

        secs = 0.0
        try:
            secs = media.duration(dest)
            poster = media.first_frame(dest, work / "poster.jpg", width=1280)
        except Exception:  # noqa: BLE001
            poster = None
        if not secs or poster is None or not Path(poster).is_file():
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "OpenSoul can't read that clip. Use an MP4 (H.264) clip.")
    keep = ext in UPLOAD_VIDEO and _keeper_is_still(s)  # a clip wins over a still keeper (the rule of OS-058)
    _err(st.add_version, pid, sid, take=take, file=sb.rel_path(dest), poster=sb.rel_path(poster), kind="upload",
         label="Uploaded", note=f"Your file: {Path(file.filename).name[:80]}", keep=keep,
         settings={"source": "upload", "aspect": p.aspect})
    return _project_json(st.load(pid))


@router.post("/projects/{pid}/shots/{sid}/keeper")
def set_keeper(pid: str, sid: str, req: KeeperIn):
    st = _store()
    _err(st.set_keeper, pid, sid, req.version_id)
    return _project_json(st.load(pid))


@router.delete("/projects/{pid}/shots/{sid}/versions/{vid}")
def delete_version(pid: str, sid: str, vid: str, confirm: int = 0):
    st = _store()
    _err(st.delete_version, pid, sid, vid, bool(confirm))
    return _project_json(st.load(pid))


# ---------------------------------------------------------------- export
class StoryExportIn(BaseModel):
    song: str | None = None   # OS-024: a Music song id to play under the story ("Add the song")
    song_level: float = 0.45  # song volume under the shots (0.05-1); it goes quieter while someone talks
    fill_gaps: bool = True    # OS-065: a shot with no keeper becomes black of its Length (off: it is left out)


@router.get("/projects/{pid}/songs")
def story_songs(pid: str):
    """Finished Music songs that can go under this story; songs made for this story come first."""
    from app import music_routes as MR

    _err(_store().load, pid)
    mine = set(_music_songs_of(pid))
    out = [{"song_id": x["song_id"], "title": x.get("title") or "Song", "for_this_story": x["song_id"] in mine}
           for x in MR.list_songs()["songs"] if x.get("state") == "done"]
    return {"songs": sorted(out, key=lambda x: not x["for_this_story"])}


def _music_songs_of(pid: str) -> list[str]:
    try:
        folder = _store().project_dir(pid) / "music"
    except Exception:  # noqa: BLE001
        return []
    return [f.stem for f in folder.glob("*.json")] if folder.is_dir() else []


@router.post("/projects/{pid}/export")
def export(pid: str, req: StoryExportIn | None = None):
    """Stitch the keepers in shot order. Dry run: the same stitch over the placeholder takes, labelled preview.
    With a song, the song plays under the whole story and goes quieter while someone talks (OS-024)."""
    import time

    req = req or StoryExportIn()
    song_file, song_title = None, ""
    if req.song:
        from app import music_routes as MR

        job = MR._load(req.song)
        song_file = MR._dir(req.song) / "song.wav"
        if job.get("state") != "done" or not song_file.is_file():
            raise HTTPException(400, "OpenSoul has not finished that song. Pick another song, or export with no song.")
        song_title = job.get("title") or "the song"

    st = _store()
    p = _err(st.load, pid)
    from opensoul.demo_images import filter_export_plan

    plan = filter_export_plan(sb.export_plan(p), versions={(s.id, v.id): {"kind": v.kind, "created": v.created}
                                                          for s in p.shots for v in s.versions})
    reasons = {x["reason"] for x in plan["skipped"]}
    from opensoul.demo_images import PREVIEW_ONLY

    if plan["items"] and req.fill_gaps:  # OS-065 (only when at least one shot has a real keeper)
        plan = sb.fill_gaps(plan)
    if not plan["items"]:
        raise HTTPException(400, "The demo's Shot 1 take is a preview that stays in the app, so there's nothing to export yet. "
                                 "Make your own takes to export the story." if PREVIEW_ONLY in reasons
                            else "No approved take yet: the demo's earlier takes are kept but not exported." if "no approved take yet" in reasons
                            else "Pick a keeper take for at least one shot first.")
    work = st.project_dir(pid) / "exports" / time.strftime("%Y%m%d_%H%M%S")
    work.mkdir(parents=True, exist_ok=True)
    plan["dry_run"] = _srv()._dry()
    out = None
    note = ""
    from opensoul.media import MediaError, ffmpeg_bin

    if ffmpeg_bin():
        try:
            out = sb.render_export(plan, work)
            if song_file is not None:
                from opensoul import media

                level = min(1.0, max(0.05, float(req.song_level)))
                out = media.add_song_bed(out, song_file, out.with_name(out.stem + "_with_song.mp4"), bed_gain=level)
                plan["song"] = {"id": req.song, "title": song_title, "level": level}
        except (MediaError, sb.StoryError) as e:
            note = f"Couldn't stitch: {e}"
    else:
        note = "ffmpeg isn't installed: saved the stitch plan only."
    sb.atomic_write_json(work / "plan.json", plan)
    if plan["placeholder"] and out:
        # OS-003: say what the Preview keepers really are. Samples are clips from a real render, not stand-in cards.
        by_shot = {s.id: s for s in p.shots}
        n_sample = sum(bool(((v := by_shot[it["shot_id"]].keeper_version()) and (v.settings or {}).get("sample")))
                       for it in plan["items"] if it["shot_id"] in by_shot)
        n_ph = sum(bool(it.get("placeholder")) for it in plan["items"]) - n_sample
        from opensoul import preview_samples

        credit = preview_samples.load().get("credit") or "a real OpenSoul render"
        parts = ([f"{n_sample} {'keeper is a sample' if n_sample == 1 else 'keepers are samples'} from a real render "
                  f"({credit}), not your own {'take' if n_sample == 1 else 'takes'}."] if n_sample else []) + (
                 [f"{n_ph} {'keeper is a placeholder' if n_ph == 1 else 'keepers are placeholders'} (a concept image or "
                  "a dry-run take)."] if n_ph > 0 else [])
        note = "Preview export: " + " ".join(parts)
    if out:  # OS-061: the cut against the plan
        from opensoul import media as _m

        plan["cut_total"] = round(_m.duration(out), 2)
        sb.atomic_write_json(work / "plan.json", plan)
        planned = [float(it.get("seconds") or 0) for it in plan["items"]]
        if any(planned):
            note = (note + " " if note else "") + (f"The cut is {plan['cut_total']:.1f} s. Shots with a Length use "
                                                   "that length.")
    if song_file is not None and out:
        note = (note + " " if note else "") + f"“{song_title}” plays under the story. It goes quieter when someone talks."
    if plan.get("filled") and out:
        names = ", ".join(f"{x['index']}" for x in plan["filled"][:8])
        note = (note + " " if note else "") + (f"Shot {names} has no keeper yet, so the cut shows black for its length."
                                               if len(plan["filled"]) == 1 else
                                               f"Shots {names} have no keeper yet, so the cut shows black for their length.")
    if plan["skipped"]:
        n_prev = sum(x["reason"] == PREVIEW_ONLY for x in plan["skipped"])
        rest = len(plan["skipped"]) - n_prev
        what = "no approved take yet" if "no approved take yet" in reasons else "no keeper yet"
        parts = ([f"Skipped {rest} shot(s) with {what}."] if rest else []) + (
            [f"Skipped {n_prev} demo preview take(s): they play in the app but aren't exported."] if n_prev else [])
        note = (note + " " if note else "") + " ".join(parts)
    return {"plan": plan, "output_url": _url(sb.rel_path(out)) if out else None,
            "download_url": (_url(sb.rel_path(out)) + "&download=1") if out else None,
            "output_path": str(out) if out else None, "plan_path": str(work / "plan.json"), "note": note}
