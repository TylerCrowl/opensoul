"""Quick shots (decision D1, Oct 18 2026): a single shot is always a project.

Create's one-off renders live in ``DATA/outputs/shots/<id>/``. Each one becomes a shot in the project "Quick shots"
(``DATA/projects/quick-shots/``) with one take that points at the files **in place**: nothing is copied, moved or
deleted. ``record()`` is what the app calls after a new quick shot renders; the CLI brings older ones in:

    python -m opensoul.migrate --data <DATA dir>            # dry run: prints the plan, writes nothing
    python -m opensoul.migrate --data <DATA dir> --apply    # backs up project.json first, then adds what's missing

Idempotent: a take remembers its source folder (``settings.migrated_from``), so running it again adds nothing."""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from opensoul import storyboard as sb

QUICK_ID = "quick-shots"
QUICK_TITLE = "Shorts"  # was "Quick shots"; the id stays quick-shots, so stored stories still load
OLD_TITLES = ("Quick shots", QUICK_TITLE)
MEDIA = ("final.mp4", "lipsync.mp4", "video.mp4")


def _store(data: Path) -> sb.Store:
    return sb.Store(Path(data) / "projects")


def is_shorts(title: str | None) -> bool:
    """True when a new-story title is the Shorts story (the Shorts button sends one of these titles)."""
    return (title or "").strip().lower() in {t.lower() for t in OLD_TITLES}


def ensure_project(store: sb.Store) -> sb.Project:
    """The Shorts story, always 9:16 for new shorts.

    An old 16:9 Shorts story with no takes changes to 9:16. A story with takes stays as it is, so old takes keep their size."""
    if store.exists(QUICK_ID):
        p = store.load(QUICK_ID)
        if p.aspect != "9:16" and not any(s.versions for s in p.shots):
            p.aspect = "9:16"
            p = store.save(p)
        return p
    return store.create_project(QUICK_TITLE, pid=QUICK_ID, aspect="9:16")


def _source(out_dir: Path, data: Path) -> str:
    try:
        return Path(out_dir).resolve().relative_to(Path(data).resolve()).as_posix()
    except ValueError:
        return str(Path(out_dir).resolve())


def recorded_sources(p: sb.Project) -> set[str]:
    return {v.settings.get("migrated_from") for s in p.shots for v in s.versions if v.settings.get("migrated_from")}


def _main_file(out_dir: Path) -> Path | None:
    return next((out_dir / m for m in MEDIA if (out_dir / m).is_file()), None)


def _grab_poster(media: Path, dest: Path) -> Path | None:
    """First frame of the clip, kept in the project folder (the output folder is never written)."""
    try:
        from opensoul import media as mediamod
        return mediamod.first_frame(media, dest)
    except Exception:  # noqa: BLE001 - no ffmpeg or an odd file: the card shows "No take yet" art, nothing breaks
        return None


PREVIEW_GREYS = ((236, 236, 240), (199, 199, 207))  # app/server.py _name_card: the dry-run stand-in picture


def looks_like_preview(picture: Path | None) -> bool:
    """True when a frame is the grey dry-run name card (background + silhouette), i.e. a placeholder take."""
    if not picture or not Path(picture).is_file():
        return False
    try:
        from PIL import Image

        im = Image.open(picture).convert("RGB").resize((48, 64))
    except Exception:  # noqa: BLE001
        return False
    colors = im.getcolors(48 * 64) or []
    near = sum(n for n, c in colors if any(sum(abs(a - b) for a, b in zip(c, g)) <= 24 for g in PREVIEW_GREYS))
    return near / (48 * 64) >= 0.85


def record(data: Path, out_dir: Path, *, name: str = "", camera: str = "static", effect: str | None = None,
           line: str = "", prompt: str = "", seed: int | None = None, placeholder: bool = False,
           title: str = "") -> tuple[str, str] | None:
    """Add one rendered quick shot to "Quick shots" (files referenced in place). Returns (shot id, take id), or None
    when the folder has no video or is already recorded."""
    data, out_dir = Path(data), Path(out_dir)
    media = _main_file(out_dir)
    if media is None:
        return None
    sb.set_data_dir(data)
    store = _store(data)
    p = ensure_project(store)
    src = _source(out_dir, data)
    if src in recorded_sources(p):
        return None
    when = datetime.fromtimestamp(media.stat().st_mtime, tz=timezone.utc).astimezone()
    beat = title or f"{name.strip() or 'Short'} · {(effect or camera or 'shot').replace('_', ' ')} · {when:%b %d %H:%M}"
    beat = beat.replace("{when}", f"{when:%b %d, %H:%M}")
    shot = store.add_shot(QUICK_ID, beat, prompt=prompt[:2000], characters=[name] if name.strip() else [],
                          camera=camera or "static", line=line or "")
    poster = next((out_dir / n for n in ("poster.jpg", "start.png", "frame.png") if (out_dir / n).is_file()), None)
    if poster is None:
        poster = _grab_poster(media, data / "projects" / QUICK_ID / "posters" / f"{shot.id}.jpg")
    if not placeholder and looks_like_preview(poster):
        placeholder = True  # a dry-run stand-in: labelled Preview, never Final
    quality = "draft" if placeholder else "final" if (out_dir / "voice.wav").is_file() or (out_dir / "lipsync.mp4").is_file() else "draft"
    v = store.add_version(QUICK_ID, shot.id, file=sb.rel_path(media), poster=sb.rel_path(poster) if poster else None,
                          prompt=prompt[:4000], seed=seed, kind="preview" if placeholder else "render",
                          placeholder=placeholder, label="Short" + (" · preview" if placeholder else ""),
                          settings={"migrated_from": src, "quality": quality, "effect": effect or "",
                                    "source": "create"})
    return shot.id, v.id


def plan(data: Path) -> list[dict]:
    """What --apply would add: one entry per output folder with a video that isn't in "Quick shots" yet."""
    data = Path(data)
    root = data / "outputs" / "shots"
    if not root.is_dir():
        return []
    done: set[str] = set()
    store = _store(data)
    if store.exists(QUICK_ID):
        done = recorded_sources(store.load(QUICK_ID))
    out = []
    for d in sorted((x for x in root.iterdir() if x.is_dir()), key=lambda x: x.stat().st_mtime):
        media = _main_file(d)
        src = _source(d, data)
        if media is not None and src not in done:
            out.append({"folder": src, "media": media.name})
    return out


def backup(data: Path) -> Path | None:
    """Copy project.json of "Quick shots" aside before any change (never overwrites an older backup)."""
    f = Path(data) / "projects" / QUICK_ID / "project.json"
    if not f.is_file():
        return None
    dest = f.with_name(f"project.json.bak-{datetime.now():%Y%m%d-%H%M%S}")
    i = 2
    while dest.exists():
        dest, i = f.with_name(f"{dest.name}-{i}"), i + 1
    shutil.copy2(f, dest)
    return dest


def apply(data: Path) -> dict:
    todo = plan(data)
    bak = backup(data)
    added = []
    for t in todo:
        r = record(data, Path(data) / t["folder"], title="Short · {when}")
        if r:
            added.append({**t, "shot": r[0], "take": r[1]})
    return {"backup": str(bak) if bak else None, "added": added}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opensoul.migrate", description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", required=True, help="the app's DATA folder (OPENSOUL_DATA)")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    a = ap.parse_args(argv)
    data = Path(a.data)
    if not data.is_dir():
        print(f"No such folder: {data}", file=sys.stderr)
        return 2
    todo = plan(data)
    print(f"{len(todo)} quick shot(s) to add to '{QUICK_TITLE}' (files stay where they are):")
    for t in todo:
        print(f"  {t['folder']}  ({t['media']})")
    if not a.apply:
        print("Dry run: nothing written. Add --apply to do it.")
        return 0
    r = apply(data)
    print(f"Backup: {r['backup'] or 'none needed (no Quick shots project yet)'}")
    print(f"Added {len(r['added'])} take(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
