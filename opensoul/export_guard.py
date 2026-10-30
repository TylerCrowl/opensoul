"""Files that never leave the app in an export (story cut, vertical clip, git archive / release zip).

Every file under a ``concepts/`` (or ``concept/``) folder is out: Lumi's concept images include one made with a
closed (non-open) image generator, and the others are retired looks. ``DERIVED`` lists shipped files that descend
from one (gate hits, crops, the demo film, the preset tile clips). The list is also kept for git in ``.gitattributes`` (export-ignore)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONCEPT_DIRS = {"concepts", "concept"}
# Shipped files that descend from a closed-generator image (the release check's hash gate, Oct 18 23:25, plus one
# crop of a concept). They stay in the working tree for the live demo until replaced, but never leave in an export.
DERIVED = {
    "assets/demo_samples/lumi_video_poster.png",          # 9:16 crop of assets/lumi/concepts/v3_cold_open.jpg
    "assets/lumi/lumi_character_sheet_v3.jpg",            # Lumi v3 (from concepts/lumi_real_B.jpg)
    "assets/lumi/lumi_character_sheet_v3_trimmed.jpg",
    "assets/lumi/lumi_ref_v3.jpg",
    "assets/lumi/lumi_ref_v3_full_trim.jpg",
    "assets/lumi/lumi_ref_v3_trim.jpg",
    "assets/demo_samples/lumi_still_01_front.png",        # near matches of the v3 refs
    "assets/demo_samples/lumi_pack/refs/ref_00.png",
    "assets/demo_samples/lumi_pack/refs/ref_01.png",
    "assets/demo_audited/konbini_master.jpg",             # near match of MASTER_PLATE_konbini.png
    "assets/demo_audited/shot01_cold_open_v8e_f24.jpg",   # near matches of the s01 start frame
    "assets/demo_audited/shot01_cold_open_v8f_f28.jpg",
    # Content review, Oct 18 23:37: also out of every export (the gate can't see videos or crops), kept in the live app.
    # (a) the approved Shot 1 take (v8f film) and the stills cut from it
    "assets/demo_audited/shot01_doodling_v8f.mp4",
    "assets/demo_audited/lumi_card_v8f_f18.jpg",
    "assets/demo_audited/tile_still_v8f_f24.jpg",
    # (b) every other demo_audited picture cut from the konbini stage plate or a Lumi render
    "assets/demo_audited/konbini_window_side.jpg",
    "assets/demo_audited/konbini_register.jpg",
    "assets/demo_audited/stage_konbini_sheet_v6.jpg",
    "assets/demo_audited/lumi_talk_l04_s171_f13_c318.jpg",
    "assets/demo_audited/lumi_card_v8e_f24.jpg",
    "assets/demo_audited/tile_still_v8e_f24.jpg",
    # (c) the camera and effect tile clips (ffmpeg moves over concepts/v3_* and the v3 Lumi stills)
    "assets/preset_thumbs/camera/crash_zoom.mp4",
    "assets/preset_thumbs/camera/dolly_in.mp4",
    "assets/preset_thumbs/camera/dolly_left.mp4",
    "assets/preset_thumbs/camera/dolly_out.mp4",
    "assets/preset_thumbs/camera/dolly_right.mp4",
    "assets/preset_thumbs/camera/dolly_zoom.mp4",
    "assets/preset_thumbs/camera/fpv.mp4",
    "assets/preset_thumbs/camera/jib_down.mp4",
    "assets/preset_thumbs/camera/jib_up.mp4",
    "assets/preset_thumbs/camera/push_in_gentle.mp4",
    "assets/preset_thumbs/camera/static.mp4",
    "assets/preset_thumbs/effects/day_to_night.mp4",
    "assets/preset_thumbs/effects/earth_zoom_out.mp4",
    "assets/preset_thumbs/effects/outfit_switch.mp4",
    # (d) Content review, Oct 19 00:03: the other crops of the v3 sheet (not flagged by the gate)
    "assets/demo_samples/lumi_sheet_preview.jpg",
    "assets/demo_samples/lumi_still_02_side.png",
    "assets/demo_samples/lumi_still_03_close.png",
    "assets/demo_samples/lumi_pack/refs/ref_02.png",
}

# Whole shipped folders left out of every export (release check, Oct 19 00:44): the demo Lumi pack's pack.json
# points at refs/ref_00..02.png, which are in DERIVED, so a release would ship a pack with broken pictures.
# The live app keeps it; a release simply has no Lumi sample (the server skips a missing pack).
DERIVED_DIRS = {"assets/demo_samples/lumi_pack/"}


# Pre-rebuild character art (release check, Oct 19 01:13): the v1 Lumi/Mio/Ren sheets and refs, the retired-look
# reject sample, the demo GIF (untraced source) and the credits card. Out of every export; the live app keeps them
# until the text-only rebuild assets land (listed in the live-UI swap list kept with the audit notes).
PRE_REBUILD = {
    "assets/lumi/lumi_character_sheet_v1.jpg",
    "assets/lumi/lumi_ref_00.jpg",
    "assets/lumi/lumi_still_01.jpg",
    "assets/mio/mio_character_sheet_v1.jpg",
    "assets/mio/mio_ref_00.jpg",
    "assets/ren/ren_character_sheet_v1.jpg",
    "assets/ren/ren_ref_00.jpg",
    "assets/demo_samples/lumi_still_reject_demo.png",
    "docs/media/opensoul_demo.gif",
    "docs/media/credits/credits_card.png",
}


# Internal working files that never go public (the release check's gate triage, Oct 18): folders end with "/".
NOT_PUBLIC = {
    "notes/",            # internal render notes and scripts
    "docs/drafts/",      # superseded drafts; the live submission texts are kept outside the repo
    "scripts/box_bootstrap.sh",  # private build-box setup
    "docs/WIN_CHECKLIST.md",     # internal planning notes
    "docs/OWNER_ASKS.md",
}


def not_public(rel: str) -> bool:
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in NOT_PUBLIC)


def blocked(path: str | Path | None) -> bool:
    """True for a concept image (or a crop of one) that must not be exported."""
    if not path:
        return False
    p = Path(str(path))
    if any(part.lower() in CONCEPT_DIRS for part in p.parts):
        return True
    try:
        rel = p.resolve().relative_to(ROOT.resolve()).as_posix() if p.is_absolute() else p.as_posix()
    except ValueError:
        return False
    return rel in DERIVED or rel in PRE_REBUILD or any(rel.startswith(d) or rel == d.rstrip("/") for d in DERIVED_DIRS) or not_public(rel)


def concept_files() -> list[Path]:
    """Every concept file in the repo (for the deny list)."""
    skip = {".git", ".venv", "node_modules", "data"}
    return sorted(f for f in ROOT.rglob("*") if f.is_file() and not (set(f.relative_to(ROOT).parts) & skip)
                  and any(x.lower() in CONCEPT_DIRS for x in f.relative_to(ROOT).parts[:-1]))
