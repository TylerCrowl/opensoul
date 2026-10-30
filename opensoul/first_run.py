"""First-run examples slot: what a first-time visitor sees (presets/first_run.json, decision D3 of Oct 18 2026).

Order: the film, but only with ``"audited": true`` and an existing file; else the accepted re-render tiles listed in
``tiles.items`` (each ``{"preset", "kind", "video", "status": "accepted"}``) that exist; else the preset tile clips
already in the repo. Media must live under assets/ or docs/media/ inside the repo, so nothing else can be shown."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "presets" / "first_run.json"
ALLOWED = ("assets/", "docs/media/")


def _media(rel: str | None, root: Path) -> tuple[str, Path] | None:
    """(url, file) for a repo-relative media path that exists inside an allowed folder; None otherwise."""
    rel = str(rel or "").strip().lstrip("/")
    if not rel or ".." in Path(rel).parts or not rel.startswith(ALLOWED):
        return None
    p = (root / rel).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError:
        return None
    if not p.is_file():
        return None
    return ("/" + rel if rel.startswith("assets/") else f"/api/file?path={rel}"), p  # a repo key, never a full path


def load(config: Path | None = None, root: Path | None = None, presets: dict | None = None, images: dict | None = None) -> dict:
    """``images``: the presets/demo_images.json content (which preset clips have passed); read from disk when None."""
    root = root or ROOT
    try:
        cfg = json.loads((config or CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    film = cfg.get("film") or {}
    if film.get("audited") is True:
        v = _media(film.get("video"), root)
        if v:
            poster = _media(film.get("poster"), root)
            return {"mode": "film", "title": film.get("title") or "", "items": [
                {"title": film.get("title") or "", "video_url": v[0], "poster_url": poster[0] if poster else None,
                 "label": "Made with OpenSoul"}]}
    tiles = cfg.get("tiles") or {}
    items = []
    for t in tiles.get("items") or []:
        if t.get("status") != "accepted":
            continue
        v = _media(t.get("video"), root)
        if v:
            items.append({"title": t.get("title") or t.get("preset") or "", "video_url": v[0], "poster_url": None,
                          "label": t.get("kind") or ""})
    if items:
        return {"mode": "tiles", "title": tiles.get("title") or "Example moves", "items": items}
    if presets is None:
        from opensoul.presets import load_presets

        presets = load_presets()
    from opensoul.demo_images import clip_allowed, load as demo_images

    allowed = demo_images() if images is None else images
    items, seen = [], set()
    for kind in ("camera", "effects"):
        for p in presets.get(kind, []):
            if not clip_allowed(p.get("id"), allowed):
                continue  # only review-passed clips (presets/demo_images.json)
            motion = json.dumps(p.get("expect_motion"))
            if motion in seen:
                continue  # examples must look different: Dolly in and Gentle push-in are both a push-in
            seen.add(motion)
            v = _media(p.get("thumbnail"), root)
            if v:
                items.append({"title": p.get("label") or p.get("id"), "video_url": v[0], "poster_url": None,
                              "label": "Camera move" if kind == "camera" else "Effect"})
    return {"mode": "demo", "title": cfg.get("fallback_title") or "Example moves", "items": items}
