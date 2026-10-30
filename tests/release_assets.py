"""Release archives (``git archive``) leave some demo files out (opensoul/export_guard.py) and have no ``.git``.
Tests that need either skip there with a clear reason instead of failing; in the dev tree they always run."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

LUMI_REFS = ("assets/demo_samples/lumi_pack/refs/ref_00.png", "assets/demo_samples/lumi_pack/refs/ref_01.png",
             "assets/demo_samples/lumi_pack/refs/ref_02.png")  # the demo Lumi's pictures
LUMI_PACK = "assets/demo_samples/lumi_pack/pack.json"  # the whole folder is left out of releases (DERIVED_DIRS)
DEMO_POSTER = "assets/demo_audited/placeholder_tile.jpg"  # tile_still in presets/demo_images.json
V8F_TAKE = "assets/demo_audited/shot01_doodling_v8f.mp4"
CONCEPT = "assets/lumi/concepts/lumi_real_B.jpg"
TILE_CLIP = "assets/preset_thumbs/camera/static.mp4"


def _all_derived() -> tuple[str, ...]:
    from opensoul.export_guard import DERIVED

    return tuple(sorted(DERIVED))


def requires_demo_asset(*paths: str):
    """Skip unless every repo-relative path exists (no paths: every file export_guard keeps out of releases)."""
    paths = paths or _all_derived()
    missing = [p for p in paths if not (ROOT / p).is_file()]
    more = f" (+{len(missing) - 1} more)" if len(missing) > 1 else ""
    return pytest.mark.skipif(bool(missing), reason=(
        f"needs {missing[0]}{more}, a demo file that release archives leave out (opensoul/export_guard.py)" if missing else ""))


requires_git = pytest.mark.skipif(not (ROOT / ".git").exists(),
                                  reason="needs the git checkout (.git); release archives have none")
