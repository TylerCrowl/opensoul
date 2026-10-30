"""Which pictures the default UI may show for the demo cast, the demo story and the example tiles (presets/demo_images.json).

Review-passed sources only; anything not listed shows a stylised placeholder or the move's glyph card. Display
only: these never change which files a render uses. Media must live under assets/ in the repo."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "presets" / "demo_images.json"


def load(config: Path | None = None) -> dict:
    try:
        return json.loads((config or CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# Stand-ins by slot: a scene (shot card, start card, take poster), a stage plate, a move tile, a stage angle. A cast
# member's own card picture stands in for their portrait; the person silhouette is never used for a scene or a set.
PLACEHOLDERS = {"scene": "assets/demo_audited/placeholder_shot.jpg", "stage": "assets/demo_audited/placeholder_stage.jpg",
                "tile": "assets/demo_audited/placeholder_tile.jpg", "frame": "assets/demo_audited/placeholder_frame.svg"}
_VID = {".mp4", ".webm", ".mov", ".gif"}


def url(rel: str | None, root: Path | None = None, kind: str | None = None) -> str | None:
    """'/assets/...' for a repo asset that exists, else None (a missing file never becomes a broken image).

    A file the UI must not show (an old pre-rebuild design in ``pre_rebuild_hide``, or one export_guard lists as
    derived from a closed-generator image: DERIVED, DERIVED_DIRS, PRE_REBUILD, concept folders) is never handed out:
    a picture becomes the placeholder for its ``kind`` of slot (else the character's card picture, else the scene
    placeholder) and a clip becomes None. Whatever presets/demo_images.json points at."""
    rel = str(rel or "").strip().lstrip("/")
    if not rel.startswith("assets/") or ".." in Path(rel).parts or not ((root or ROOT) / rel).is_file():
        return None
    sub = _stand_in(rel, kind)
    return ("/" + sub if sub else None) if sub is not None else "/" + rel


def _stand_in(rel: str, kind: str | None) -> str | None:
    """None when ``rel`` may be shown; else the placeholder to show instead ("" for a clip: nothing)."""
    from opensoul.export_guard import blocked

    if Path(rel).name.startswith("placeholder_"):
        return None
    old = pre_rebuild_name(ROOT / rel)
    if not old and not blocked(rel):
        return None
    if Path(rel).suffix.lower() in _VID:
        return ""
    if kind in PLACEHOLDERS:
        return PLACEHOLDERS[kind]
    card = ((load().get("cast") or {}).get(old or "") or {}).get("card") if old else None
    return card if card and Path(card).name.startswith("placeholder_") else PLACEHOLDERS["scene"]


def _key(name: str) -> str:
    return " ".join(str(name or "").split()).lower()


_IMG = {".png", ".jpg", ".jpeg", ".webp"}


def pre_rebuild_name(path, data_dir: Path | None = None, cfg: dict | None = None) -> str | None:
    """The cast name whose old (pre-rebuild) design this picture shows, else None (pre_rebuild_hide)."""
    cfg = load() if cfg is None else cfg
    h = cfg.get("pre_rebuild_hide") or {}
    try:
        p = Path(path).resolve()
    except (OSError, TypeError, ValueError):
        return None
    if p.suffix.lower() not in _IMG:
        return None
    for rel, name in (h.get("dirs") or {}).items():
        if p.is_relative_to((ROOT / rel).resolve()):
            return name
    if data_dir is not None:
        packs = (Path(data_dir) / "packs").resolve()
        if p.is_relative_to(packs) and len(p.relative_to(packs).parts) > 1:
            folder = packs / p.relative_to(packs).parts[0]
            base = folder.name.lower().rsplit("_", 1)
            key = base[0] if len(base) == 2 and base[1].isdigit() else folder.name.lower()
            if key in {_key(n) for n in h.get("pack_names") or []}:
                try:
                    meta = json.loads((folder / "pack.json").read_text(encoding="utf-8")).get("meta") or {}
                except (OSError, ValueError):
                    meta = {}
                if ((meta.get("origin") or {}).get("kind")) != "text":  # a new character made from words is current
                    return key
    return None


def cast_card(name: str, cfg: dict | None = None) -> dict:
    """{'card_url', 'card_placeholder', 'card_note', 'more_example'} for a cast member (empty values when not listed)."""
    cfg = load() if cfg is None else cfg
    c = (cfg.get("cast") or {}).get(_key(name)) or {}
    return {"card_url": url(c.get("card")), "card_placeholder": bool(c.get("placeholder")),
            "card_note": c.get("note") or "",
            "more_example": _key(name) in {_key(n) for n in cfg.get("more_examples") or []}}


def tile_still(cfg: dict | None = None) -> str | None:
    """The one passed still the camera/effect tiles show under their glyphs while no clip has passed."""
    cfg = load() if cfg is None else cfg
    return url((cfg.get("tile_still") or {}).get("image"), kind="tile")


def first_run_still(cfg: dict | None = None) -> dict | None:
    """The start card's still ({image_url, title, caption, alt}) or None."""
    cfg = load() if cfg is None else cfg
    c = cfg.get("first_run_still") or {}
    u = url(c.get("image"), kind="scene")
    return {"image_url": u, "title": c.get("title") or "", "caption": c.get("caption") or "", "alt": c.get("alt") or ""} if u else None


def clip_allowed(preset_id: str, cfg: dict | None = None) -> bool:
    """Only clips listed as passed are shown; without the config every clip is allowed (old behaviour)."""
    cfg = load() if cfg is None else cfg
    pc = cfg.get("preset_clips")
    return True if pc is None else preset_id in (pc.get("allowed") or [])


def _approved(p: dict) -> dict:
    """{beat: (ids of stored takes, [shipped take entries])} from a story's approved_takes. An entry is either a
    stored take id ("v9") or a shipped take {"id", "video", "poster", ...} served from assets/ (no data writes)."""
    out = {}
    for k, v in (p.get("approved_takes") or {}).items():
        ids, shipped = set(), []
        for e in v or []:
            if isinstance(e, dict):
                if e.get("id") and url(e.get("video")):
                    shipped.append(e)
            elif e:
                ids.add(str(e))
        out[_key(k)] = (ids, shipped)
    return out


def _shipped_version(e: dict) -> dict:
    return {"id": e["id"], "take": 0, "take_id": f"approved-{e['id']}", "file": e["video"], "poster": e.get("poster"),
            "prompt": "", "edit": "", "seed": None, "settings": {"quality": "final"}, "scores": {},
            "created": e.get("created") or "2026-10-18T22:54:00-04:00", "kind": "render", "placeholder": False,
            "label": e.get("label") or "Approved take", "status": "ready", "note": e.get("note") or "", "based_on": None,
            "poster_url": url(e.get("poster"), kind="scene"), "video_url": url(e["video"]), "missing": False, "shipped": True,
            "preview_only": _no_export(e["video"])}


PREVIEW_ONLY = "demo preview, stays in the app"


def _no_export(path) -> bool:
    """The demo's shipped takes are kept out of every export (opensoul/export_guard.py): they play in the app only."""
    from opensoul.export_guard import blocked

    return blocked(path)


def _hidden(p: dict, v: dict, ids: set) -> bool:
    """A demo take is hidden unless approved. Only what existed at the audit is hidden: the seeded concept stills and
    takes created before ``hide_takes_before``; a take the user makes afterwards shows as usual."""
    if v.get("id") in ids:
        return False
    cut = p.get("hide_takes_before")
    if not cut or v.get("kind") == "concept":
        return True
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(v.get("created"))) < datetime.fromisoformat(cut)
    except (TypeError, ValueError):
        return True


def shot_text(pid: str, beat: str, stored: str, cfg: dict | None = None) -> str:
    """The demo story's description for a shot: the script-matched text while the stored one is still an old default."""
    cfg = load() if cfg is None else cfg
    t = (((cfg.get("projects") or {}).get(pid) or {}).get("shot_text") or {}).get(beat) or {}
    return t["prompt"] if t.get("prompt") and (stored or "").strip() in {x.strip() for x in t.get("replaces") or []} else stored


def take_approved(pid: str, beat: str, vid: str, cfg: dict | None = None) -> bool:
    """False only for a demo-story take that is not on that story's approved_takes allow-list."""
    cfg = load() if cfg is None else cfg
    p = (cfg.get("projects") or {}).get(pid)
    if not p:
        return True
    ids, shipped = _approved(p).get(_key(beat or ""), (set(), []))
    return vid in ids or any(e["id"] == vid for e in shipped)


def filter_export_plan(plan: dict, cfg: dict | None = None, versions: dict | None = None) -> dict:
    """Demo story: unapproved keepers are skipped (listed, never stitched); a shot whose stored keeper isn't approved
    exports its first shipped approved take instead. Other stories are unchanged."""
    cfg = load() if cfg is None else cfg
    p = (cfg.get("projects") or {}).get(plan.get("project", ""))
    if not p:
        return plan
    appr = _approved(p)
    keep, skipped = [], []
    for it in plan["items"]:
        ids = appr.get(_key(it.get("beat", "")), (set(), []))[0]
        meta = (versions or {}).get((it.get("shot_id"), it.get("take"))) or {"id": it.get("take")}
        if not _hidden(p, {**meta, "id": it.get("take")}, ids):
            keep.append(it)
        else:
            skipped.append({"index": it["index"], "shot_id": it["shot_id"], "beat": it["beat"], "reason": "no approved take yet"})
    for x in plan["skipped"] + skipped:
        shipped = appr.get(_key(x["beat"]), (set(), []))[1]
        if shipped and _no_export(shipped[0]["video"]):
            plan["skipped"] = [y for y in plan["skipped"] if y is not x] + [{**x, "reason": PREVIEW_ONLY}]
        elif shipped:
            e = shipped[0]
            keep.append({"index": x["index"], "shot_id": x["shot_id"], "beat": x["beat"], "take": e["id"], "take_id": f"approved-{e['id']}",
                         "source": e["video"], "source_kind": "video", "placeholder": False, "label": e.get("label") or "Approved take"})
        elif x not in plan["skipped"]:
            plan["skipped"].append(x)
    done = {it["index"] for it in keep}
    plan["skipped"] = sorted((x for x in plan["skipped"] if x["index"] not in done), key=lambda x: x["index"])
    plan["items"] = sorted(keep, key=lambda it: it["index"])
    plan["placeholder"] = any(it["placeholder"] for it in keep)
    return plan


def apply_project(d: dict, cfg: dict | None = None) -> dict:
    """Swap the demo story's card and stage pictures for the listed ones (in place; the JSON sent to the UI)."""
    cfg = load() if cfg is None else cfg
    p = (cfg.get("projects") or {}).get(d.get("id"))
    if not p:
        return d
    cards = {_key(k): v for k, v in (p.get("shot_cards") or {}).items()}
    approved = _approved(p)
    for s in d.get("shots", []):
        if "prompt" in s:
            s["prompt"] = shot_text(d.get("id", ""), s.get("beat") or "", s["prompt"], cfg)
        beat = _key(s.get("beat") or s.get("title") or "")
        ok, shipped = approved.get(beat, (set(), []))
        # Allow-list: a take plays (take viewer, Review, queue) only once it is listed as approved. Nothing is deleted;
        # an unapproved take just has no picture or video in what the UI gets.
        for v in s.get("versions", []):
            if not _hidden(p, v, ok):
                continue
            v["unapproved"] = True
            v["poster_url"] = v["video_url"] = None
            # Its old wording (prompt, edit, note: cat, ancient book, elf) never reaches the UI either; the file keeps it.
            v["prompt"] = v["edit"] = ""
            v["note"] = p.get("hidden_take_text") or ""
            v["settings"] = {k: x for k, x in (v.get("settings") or {}).items() if k in ("quality", "camera", "aspect")}
        # Shipped approved takes come first; one stands in as the keeper while the stored keeper isn't approved.
        have = {v.get("id") for v in s.get("versions", [])}
        extra = [_shipped_version(e) for e in shipped if e["id"] not in have]
        s["versions"] = extra + s.get("versions", [])
        cur = next((v for v in s["versions"] if v.get("id") == s.get("keeper")), None)
        if extra and (cur is None or cur.get("unapproved")):
            s["stored_keeper"] = s.get("keeper")
            s["keeper"] = extra[0]["id"]
        k = next((v for v in s.get("versions", []) if v.get("id") == s.get("keeper")), None)
        if not k:
            continue
        c = cards.get(beat)
        # A placeholder card shows as the labelled "No take yet" tile, the same as every other shot without a take.
        pic = url(c.get("card"), kind="scene") if c and not c.get("placeholder") else None
        # The card shows the listed passed frame; with none (and no approved keeper) it is the plain "No take yet" card.
        k["card_url"] = s["keeper_poster_url"] = pic or k.get("poster_url")
        k["card_audited"] = bool(pic)
        k["card_placeholder"] = bool(c and c.get("placeholder"))  # a neutral stand-in while the look is rebuilt
        k["card_blank"] = not k["card_url"]
    stages = {_key(k): v for k, v in (p.get("stage") or {}).items()}
    for loc in d.get("locations", []):
        st = stages.get(_key(loc.get("name")))
        if not st:
            continue
        if loc.get("image_url"):
            loc["image_url"] = url(st.get("master"), kind="stage") or url(st.get("other_angles"), kind="frame")
        if loc.get("sheet_url"):
            loc["sheet_url"] = url((st.get("sheet") or {}).get("image"), kind="stage")
        if loc.get("empty_url") and st.get("empty"):
            loc["empty_url"] = url(st["empty"], kind="stage")  # the story's own empty-plate picture (data file untouched)
        if st.get("placeholder"):
            loc["placeholder"] = True
            loc["status"] = st.get("status") or "Plate being rebuilt"  # never "Ready" while the plate is a stand-in
        angles = {_key(k): v for k, v in (st.get("angles") or {}).items()}
        for a in loc.get("angles", []):
            if not a.get("image_url"):
                continue
            m = angles.get(_key(a.get("name")))
            a["image_url"] = url(m.get("image"), kind="frame") if m else url(st.get("other_angles"), kind="frame")
            a["audited"] = bool(m)
    return d
