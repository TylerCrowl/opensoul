"""Workflow 08 (scene composer) inputs from scripts/story_frames.py name real nodes."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("story_frames", ROOT / "scripts/story_frames.py")
sf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sf)


def test_frame_inputs_fill_three_images_and_match_workflow():
    from opensoul.comfy_client import apply_inputs

    inp = sf.frame_inputs({"name": "x", "images": ["a.png", "b.png"], "prompt": "p"}, 5)
    assert [inp[n]["image"] for n in ("5", "51", "52")] == ["a.png", "b.png", "b.png"]
    assert inp["3"]["seed"] == 5 and inp["8"] == {"width": 1344, "height": 768}
    apply_inputs(json.loads(sf.WF.read_text()), inp)
    with pytest.raises(ValueError):
        sf.frame_inputs({"name": "x", "images": [], "prompt": "p"}, 1)
