"""Character pack round-trip tests."""

from __future__ import annotations

from pathlib import Path

from opensoul.character_pack import CharacterPack
from release_assets import LUMI_PACK, requires_demo_asset

ROOT = Path(__file__).resolve().parents[1]
PIXEL = ROOT / "assets" / "example_character" / "pixel_reference.png"


def test_save_load_roundtrip(tmp_path: Path):
    pack = CharacterPack(
        name="Pixel",
        prompt_lock="cute geometric robot",
        seed=7,
        ref_images=[str(PIXEL)],
        notes="test",
    )
    pack.save(tmp_path / "pixel")
    loaded = CharacterPack.load(tmp_path / "pixel")
    assert loaded.name == "Pixel"
    assert loaded.seed == 7
    assert len(loaded.ref_images) == 1
    assert Path(loaded.ref_images[0]).is_file()
    assert "cute geometric robot" in loaded.prompt_with_lock("in a field")


def test_prompt_with_lock_empty_scene():
    p = CharacterPack(name="x", prompt_lock="locked look")
    assert p.prompt_with_lock("") == "locked look"


def test_pronoun_is_an_optional_field_that_round_trips(tmp_path: Path):
    import json

    from opensoul import lipsync as L

    assert CharacterPack(name="x", prompt_lock="y").pronoun == "they"          # default
    for pro in ("she", "he", "they", "she/her"):
        d = tmp_path / pro.replace("/", "_")
        CharacterPack(name="Lumi", prompt_lock="lock", pronoun=pro).save(d)
        assert json.loads((d / "pack.json").read_text())["pronoun"] == pro
        loaded = CharacterPack.load(d)
        assert loaded.pronoun == pro
        assert L.pronoun_for_pack_dir(d) == L.pronoun_key(pro)                 # the lip-sync prompt sees it
        loaded.save(d)                                                          # save again: unchanged
        assert CharacterPack.load(d).pronoun == pro


def test_old_packs_without_pronoun_load_as_they_or_their_legacy_key(tmp_path: Path):
    import json

    for name, extra, want in (("none", {}, "they"), ("plural", {"pronouns": "he/him"}, "he"),
                              ("meta", {"meta": {"pronoun": "she"}}, "she")):
        d = tmp_path / name
        d.mkdir()
        (d / "pack.json").write_text(json.dumps({"name": name, "prompt_lock": "p", **extra}))
        assert CharacterPack.load(d).pronoun == want


@requires_demo_asset(LUMI_PACK)
def test_shipped_lumi_pack_loads_its_pronoun():
    assert CharacterPack.load((ROOT / LUMI_PACK).parent).pronoun == "she"
