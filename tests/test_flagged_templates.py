"""Experimental story templates behind feature flags (presets/story_templates_flagged/, docs/TEMPLATES.md): off by
default, so New story -> Start from a template lists exactly what it did before."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from opensoul import storyboard as SB

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ("OPENSOUL_FEATURE_MUSIC_VIDEO_TEMPLATE", "OPENSOUL_FEATURE_UGC_TEMPLATES")


@pytest.fixture(autouse=True)
def no_flags(monkeypatch):
    for f in FLAGS:
        monkeypatch.delenv(f, raising=False)


def _base_ids():
    ids = {"blank", SB.LUMI_TEMPLATE}
    ids |= {json.loads(f.read_text())["id"] for f in (ROOT / "presets/story_templates").glob("*.json")}
    return ids


def test_flags_off_by_default_leave_the_list_unchanged():
    assert {t["id"] for t in SB.list_templates()} == _base_ids()
    assert SB.flagged_templates() == []


def test_each_flag_turns_on_only_its_templates(monkeypatch):
    monkeypatch.setenv("OPENSOUL_FEATURE_UGC_TEMPLATES", "1")
    ids = {t["id"] for t in SB.list_templates()}
    assert ids == _base_ids() | {"ugc-ad", "product-shots"}
    monkeypatch.setenv("OPENSOUL_FEATURE_MUSIC_VIDEO_TEMPLATE", "1")
    assert "music-video" in {t["id"] for t in SB.list_templates()}
    assert all(t.get("experimental") for t in SB.flagged_templates())
    monkeypatch.setenv("OPENSOUL_FEATURE_UGC_TEMPLATES", "yes")  # only "1" turns a flag on
    assert "ugc-ad" not in {t["id"] for t in SB.list_templates()}


def test_flagged_templates_are_valid_data():
    cams = {f.stem for f in (ROOT / "presets/camera").glob("*.json")} - {"static_locked"}
    for f in (ROOT / "presets/story_templates_flagged").glob("*.json"):
        t = json.loads(f.read_text())
        assert t["flag"] in FLAGS and t["status"].startswith("stub:") and t["aspect"] in ("16:9", "9:16", "1:1"), f.name
        assert "(experimental)" in t["title"] and t["shots"], f.name
        for s in t["shots"]:
            assert s["camera"] in cams and s["beat"] and s["prompt"], (f.name, s)


def test_a_flagged_template_makes_a_story(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_FEATURE_UGC_TEMPLATES", "1")
    store = SB.Store(tmp_path)
    p = SB.create_from_template(store, "ugc-ad", lead="Mio")
    assert [s.beat for s in p.shots][:1] == ["Hook to camera"] and "Mio" in p.shots[0].prompt
