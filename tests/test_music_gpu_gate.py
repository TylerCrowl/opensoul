"""Studio GPU gate: yield to tmux sessions matching presets/music_models.json gpu_gate.yield_to (mv_* = music video)."""
from opensoul.music import gpu_gate as G
from opensoul.music import registry as R


def test_registry_yields_to_music_video_sessions():
    pats = G.patterns_from(R.load())
    assert "mv_*" in pats
    assert G.busy(["comfy", "mv_render", "mvx", "os_ui"], pats) == ["mv_render"]


def test_wait_turn_waits_then_goes_and_can_be_cancelled(monkeypatch):
    monkeypatch.delenv("OPENSOUL_GPU_GATE", raising=False)
    looks = iter([["mv_a"], ["mv_a"], []])
    waits = []
    assert G.wait_turn(("mv_*",), lister=lambda: next(looks), on_wait=waits.append, sleep=lambda s: None, interval_s=1)
    assert waits == [["mv_a"], ["mv_a"]]
    assert not G.wait_turn(("mv_*",), lister=lambda: ["mv_a"], cancelled=lambda: True, sleep=lambda s: None)
    assert not G.wait_turn(("mv_*",), lister=lambda: ["mv_a"], sleep=lambda s: None, interval_s=10, max_wait_s=30)


def test_gate_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("OPENSOUL_GPU_GATE", "off")
    assert G.wait_turn(("mv_*",), lister=lambda: ["mv_a"], sleep=lambda s: None)
