"""Text master: smile / grin / smirk words are stripped from the look before the 07z prompt is built (a smiling
master grins in every talking shot), the rest of the look stays as typed, and the build records what was removed."""
import json
import re
from pathlib import Path

import pytest

from opensoul import text_master as tm

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("look,want,gone", [
    ("a young barista with silver hair in a bun and a calm, sleepy smile", "a young barista with silver hair in a bun",
     ["and a calm, sleepy smile"]),
    ("a woman with a smile", "a woman", ["with a smile"]),
    ("a tall man, grinning widely, with a beard", "a tall man, with a beard", ["grinning widely"]),
    ("a girl with a warm smirk and freckles", "a girl with freckles", ["with a warm smirk"]),
    ("a man who smiles a lot, bald", "a man, bald", ["who smiles a lot"]),
    ("short hair, big grin", "short hair", ["big grin"]),
    ("a calm, sleepy smile, short hair", "short hair", ["a calm, sleepy smile"]),
    ("a woman smiling, silver braid", "a woman, silver braid", ["smiling"]),
    ("her crooked grin and green eyes", "green eyes", ["her crooked grin"]),
    ("smiley face, red hair", "face, red hair", ["smiley"]),
    ("a boy with grins and smirks, round glasses", "a boy, round glasses", ["with grins", "and smirks"]),
])
def test_strip_smiles(look, want, gone):
    out, removed = tm.strip_smiles(look)
    assert out == want and removed == gone
    assert not tm.SMILE_ANY.search(out)


@pytest.mark.parametrize("look", ["a weathered sailor with laugh lines and crow's feet",
                                  "a smoky-eyed woman with laugh lines", "a calm, sleepy gaze", ""])
def test_other_words_are_verbatim(look):
    assert tm.strip_smiles(look) == (look, [])


def test_the_rest_of_the_look_stays_verbatim_in_the_master_prompt():
    look = "a lanky courier with copper hair, a broad grin, laugh lines and a scar on the chin"
    parts = tm.master_parts({"look": look, "outfit": "a teal raincoat"})
    d = parts["description"]
    assert "grin" not in d and "broad" not in d
    for kept in ("a lanky courier", "copper hair", "laugh lines and a scar on the chin", "a teal raincoat"):
        assert kept in d
    assert parts["expression"] == tm.NEUTRAL


MARLOWE_V4_SHA256 = "71bd0e6c13400ca3462b072433e7ff4708ee8b7498cf914e486e6831551c8db8"  # the prompt text alone


def test_marlowe_prompt_v4():
    import hashlib

    from opensoul import zimage_master as zm

    fields = {"look": "a tall woman with a long silver-grey braid, deeply sun-tanned, wind-weathered outdoor skin, "
                      "laugh lines and a clearly visible gap between her two upper front teeth",
              "outfit": "a hip-length mustard-yellow waxed-cotton field jacket with a slightly shiny waxed finish, zip "
                        "front with a snap storm flap, brown corduroy collar and large flap pockets, open over a navy "
                        "cable-knit sweater", "age": "51-65", "style": "natural"}
    f = tm.fields(**fields)
    assert tm.without_smiles(f) == (f, [])
    parts = tm.master_parts(f)
    prompt = zm.master_prompt(parts.pop("description"), zm.load_config(ROOT / "presets" / "text_master.json", env={}),
                              **parts)
    assert prompt.count("laugh lines and a clearly visible gap between her two upper front teeth") == 1
    assert "Serious calm face, mouth relaxed and closed at the corners, lips just slightly apart, eyes" in prompt
    assert ("hair slicked straight back from the forehead and temples, both ears completely exposed, the long "
            "silver-grey braid hidden behind her back, not over her shoulder, both ears clearly visible.") in prompt
    assert "full figure from the top of the head down to just below the knees, with a little space above the head." \
        in prompt
    assert not tm.SMILE_ANY.search(prompt)
    assert hashlib.sha256(prompt.encode()).hexdigest() == MARLOWE_V4_SHA256


SMILE_WORD = re.compile(r"\b(?:smil(?:e|es|ed|ing|ey)|grin(?:s|ned|ning)?|smirk(?:s|ed|ing)?)\b", re.I)
LOOKS = ["a tall woman with a long silver-grey braid and a small gap between her front teeth", "a grinning rogue",
         "a young barista with silver hair in a bun and a calm, sleepy smile", "a man who smiles a lot, bald",
         "a smirking thief with a ponytail", "smiley face, red hair", "a vampire with fangs and pointed elf ears",
         "a sailor with a scar across his upper lip", "a courier with a shaved head", "", "a woman with a smile",
         "an elf archer with two braids who grins", "a baker with freckles and laugh lines"]


@pytest.mark.parametrize("look", LOOKS)
@pytest.mark.parametrize("outfit", ["", "a teal raincoat", "a t-shirt with a smiley print"])
def test_no_built_master_prompt_holds_smile_grin_or_smirk(look, outfit):
    from opensoul import zimage_master as zm

    for age, style in (("", ""), ("26-35", "cinematic")):
        parts = tm.master_parts({"look": look, "outfit": outfit, "age": age, "style": style})
        prompt = zm.master_prompt(parts.pop("description"), zm.load_config(env={}), **parts)
        assert not SMILE_WORD.search(prompt), prompt
        assert "both ears clearly visible" in prompt
    assert not SMILE_WORD.search(zm.master_prompt("a tall courier", zm.load_config(env={})))


def test_build_result_records_what_was_stripped(monkeypatch, tmp_path):
    import app.server as S
    from fastapi.testclient import TestClient

    monkeypatch.setattr(S, "DATA", tmp_path)
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    r = TestClient(S.app).post("/api/master", data={"look": "a young barista with silver hair and a calm, sleepy smile",
                                                    "outfit": "green apron", "name": "Test"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["look_stripped"] == ["and a calm, sleepy smile"]
    assert "smile" not in j["prompt"].replace("no smile", "")


def test_look_field_says_so_and_its_example_has_no_smile():
    html = (ROOT / "app/web/index.html").read_text()
    area = html.split('id="prompt"')[1].split("</div>")[0]
    assert "a calm, sleepy gaze" in area and "smile" not in area.split("placeholder=")[1].split('"')[1]
    assert "OpenSoul removes smiles and grins because they fail the talking-shot check." in area
