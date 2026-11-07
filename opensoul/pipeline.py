"""High-level stage orchestration (builder → stills → talking video).

GPU stages call Comfy SDK workflows. On this CPU-only box they raise a clear
error unless OPENSOUL_DRY_RUN=1 (returns placeholder paths for UI wiring).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Sequence

from opensoul.character_pack import CharacterPack
from opensoul.consistency import ConsistencyResult, score_consistency


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"


def dry_run() -> bool:
    return os.environ.get("OPENSOUL_DRY_RUN", "").strip() in {"1", "true", "yes"}


def build_character_pack(
    name: str,
    images: Sequence[str | Path],
    prompt_lock: str,
    out_dir: str | Path,
    seed: int = 42,
) -> CharacterPack:
    """Stage 1: persist a character pack. Turnaround generation needs GPU/Comfy."""
    pack = CharacterPack(
        name=name,
        prompt_lock=prompt_lock,
        seed=seed,
        ref_images=[str(p) for p in images],
        notes="Turnaround/expression sheet generation requires ComfyUI + Qwen-Image-Edit.",
    )
    pack.save(out_dir)
    # Placeholder: copy first ref as "sheet" until workflow is run on Spark
    sheet = Path(out_dir) / "turnaround_sheet.png"
    if images:
        shutil.copy2(images[0], sheet)
    (Path(out_dir) / "README.txt").write_text(
        "Character pack created. Run workflows/01_character_builder_api.json "
        "on ComfyUI to regenerate a multi-view turnaround sheet.\n",
        encoding="utf-8",
    )
    return CharacterPack.load(out_dir)


def generate_stills(
    pack_dir: str | Path,
    scene_prompt: str,
    n: int = 4,
    out_dir: str | Path = "outputs/stills",
    threshold: float = 0.78,
) -> list[tuple[Path, ConsistencyResult]]:
    """Stage 2: N stills + consistency gate.

    Dry-run: scores the pack's own refs against itself (wiring check).
    Live: runs workflows/02_consistent_stills_api.json via Comfy SDK.
    """
    pack = CharacterPack.load(pack_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    prompt = pack.prompt_with_lock(scene_prompt)
    # A pack.json can name an absolute picture outside the pack. Copying that would let any local caller
    # read files the OpenSoul user can see. Only pictures that stay inside the pack directory are used.
    from opensoul.storyboard import within

    refs = [r for r in pack.ref_images if within(r, pack_dir)]

    if dry_run() or not _comfy_reachable():
        results: list[tuple[Path, ConsistencyResult]] = []
        for i, ref in enumerate(refs[:n]):
            dest = out / f"still_{i:02d}.png"
            shutil.copy2(ref, dest)
            r = score_consistency(dest, refs, threshold=threshold, mode="mean")
            meta = {"prompt": prompt, "consistency": r.to_dict(), "dry_run": True}
            (out / f"still_{i:02d}.json").write_text(json.dumps(meta, indent=2))
            if r.passed:
                results.append((dest, r))
        return results

    from opensoul.comfy_client import run_workflow_file

    if not refs:
        return []
    paths = run_workflow_file(
        WORKFLOWS / "02_consistent_stills_api.json",
        inputs={
            "5": {"image": str(refs[0])},
            "6": {"prompt": prompt},
            "7": {"prompt": pack.negative_prompt},
            "3": {"seed": pack.seed},
        },
        output_node_id="9",
        out_dir=out,
    )
    kept: list[tuple[Path, ConsistencyResult]] = []
    for p in paths:
        r = score_consistency(p, refs, threshold=threshold, mode="mean")
        (p.with_suffix(".json")).write_text(
            json.dumps({"prompt": prompt, "consistency": r.to_dict()}, indent=2)
        )
        if r.passed:
            kept.append((p, r))
        else:
            rejected = out / "rejected"
            rejected.mkdir(exist_ok=True)
            shutil.move(str(p), rejected / p.name)
    return kept


def generate_talking_video(
    pack_dir: str | Path,
    still: str | Path,
    script: str,
    out_dir: str | Path = "outputs/video",
) -> Path:
    """Stage 3: TTS → I2V (LTX) → lip-sync → captions → MP4.

    Dry-run writes a text stub; real path needs Spark GPU + models.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stub = out / "talking_video.dry_run.txt"
    if dry_run() or not _comfy_reachable():
        stub.write_text(
            f"DRY RUN — talking video not generated.\n"
            f"still={still}\nscript={script!r}\n"
            f"pack={pack_dir}\n"
            f"On Spark: run workflows/03_tts_api.json → "
            f"04_i2v_ltx_api.json → 05_lipsync_api.json → mux captions.\n",
            encoding="utf-8",
        )
        return stub

    raise NotImplementedError(
        "Live talking-video pipeline requires ComfyUI + LTX/Wan + TTS + LatentSync "
        "on the Spark. See docs/ARCHITECTURE.md and scripts/setup_spark.sh."
    )


def _comfy_reachable() -> bool:
    import urllib.request

    url = os.environ.get("COMFY_BASE_URL", "http://127.0.0.1:8189").rstrip("/")
    try:
        with urllib.request.urlopen(url + "/api/v2/health", timeout=0.5) as resp:  # noqa: S310
            return 200 <= resp.status < 500
    except Exception:
        try:
            # proxy may not expose /health; try root
            with urllib.request.urlopen(url + "/", timeout=0.5) as resp:  # noqa: S310
                return True
        except Exception:
            return False
