"""CharacterPack.save() keeps top-level keys it doesn't model (voice_label, voice_label_notes, ...): load + save
round-trips them, and a modelled key always wins."""
import json

from opensoul.character_pack import CharacterPack


def _pack(tmp_path, **extra):
    src = tmp_path / "src"
    (src / "refs").mkdir(parents=True)
    (src / "refs" / "ref_00.png").write_bytes(b"png")
    data = {"name": "Lumi", "prompt_lock": "a woman", "seed": 5, "ref_images": ["refs/ref_00.png"], "pronoun": "she",
            "meta": {"origin": {"kind": "text"}}, **extra}
    (src / "pack.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return src


def test_voice_label_and_notes_survive_load_and_save(tmp_path):
    notes = {"engine": "an open TTS model", "license": "Apache-2.0", "status": "metadata only"}
    src = _pack(tmp_path, voice_label="F", voice_label_notes=notes)
    p = CharacterPack.load(src)
    assert p.extra == {"voice_label": "F", "voice_label_notes": notes}
    out = json.loads(p.save(tmp_path / "dst").read_text(encoding="utf-8"))
    assert out["voice_label"] == "F" and out["voice_label_notes"] == notes
    assert out["name"] == "Lumi" and out["pronoun"] == "she" and out["meta"] == {"origin": {"kind": "text"}}
    assert out["ref_images"] == ["refs/ref_00.png"] and "extra" not in out
    again = json.loads(CharacterPack.load(tmp_path / "dst").save(tmp_path / "dst2").read_text(encoding="utf-8"))
    assert again["voice_label"] == "F" and again["voice_label_notes"] == notes
    assert list(out)[-2:] == ["voice_label", "voice_label_notes"]   # after the modelled keys


def test_a_pack_without_extra_keys_saves_as_before(tmp_path):
    out = json.loads(CharacterPack.load(_pack(tmp_path)).save(tmp_path / "dst").read_text(encoding="utf-8"))
    assert "extra" not in out and set(out) == {"name", "prompt_lock", "negative_prompt", "seed", "ref_images",
                                               "lora_path", "lora_strength", "notes", "created_at", "meta", "pronoun"}
    fresh = json.loads(CharacterPack(name="X", prompt_lock="y").save(tmp_path / "x").read_text(encoding="utf-8"))
    assert "extra" not in fresh


def test_a_literal_extra_key_round_trips_too_and_modelled_keys_win(tmp_path):
    p = CharacterPack.load(_pack(tmp_path, extra={"a": 1}))
    p.extra["seed"] = 999  # can't override a modelled key
    out = json.loads(p.save(tmp_path / "dst").read_text(encoding="utf-8"))
    assert out["extra"] == {"a": 1} and out["seed"] == 5
