"""OS-063: a title or end card is a shot type. The card is drawn on this computer (Pillow, no model, no GPU), so the
words are exact; it is a still take that runs the shot's Length in the export."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from opensoul import cards
from opensoul import storyboard as sb
from opensoul.script_split import split_script

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def test_render_draws_the_words_centered_on_the_color(tmp_path):
    f = cards.render("THE LAST LIGHTHOUSE", "Coming soon", "black", tmp_path / "c.png")
    im = Image.open(f).convert("RGB")
    assert im.size == (1920, 1080)
    assert im.getpixel((5, 5)) == (0, 0, 0)
    assert im.crop((200, 400, 1720, 700)).getextrema() != ((0, 0), (0, 0), (0, 0))  # the text is there
    v = cards.render("END", "", "white", tmp_path / "v.png", aspect="9:16")
    assert Image.open(v).size == (1080, 1920)


def test_card_fields_are_checked():
    with pytest.raises(cards.CardError):
        cards.clean("x", "", "purple-ish")
    assert cards.clean(" A  B ", None, "#AABBCC") == {"card_title": "A B", "card_sub": "", "card_bg": "#aabbcc"}
    with pytest.raises(cards.CardError):
        cards.render("", "", "black", "/tmp/never.png")


def test_card_shot_makes_a_card_take_that_exports_for_its_length(client):
    p = client.post("/api/storyboard/projects", json={"title": "Cards"}).json()
    pid = p["id"]
    p = client.post(f"/api/storyboard/projects/{pid}/shots",
                    json={"beat": "Title", "kind": "card", "card_title": "THE LAST LIGHTHOUSE", "seconds": 4}).json()
    s = p["shots"][0]
    assert s["kind"] == "card" and s["characters"] == []
    base = f"/api/storyboard/projects/{pid}/shots/{s['id']}"
    r = client.post(f"{base}/card")
    assert r.status_code == 200, r.text
    s = r.json()["shots"][0]
    v = s["versions"][0]
    assert v["kind"] == "card" and s["keeper"] == v["id"] and v["poster_url"] and not v["placeholder"]
    assert client.post(f"{base}/regenerate", json={}).status_code == 400  # a card never goes to a model
    assert client.post(f"{base}/frame", json={}).status_code == 400
    item = client.post(f"/api/storyboard/projects/{pid}/export").json()["plan"]["items"][0]
    assert item["source_kind"] == "still" and item["seconds"] == 4.0


def test_switching_a_shot_to_card_and_bad_values(client):
    p = client.post("/api/storyboard/projects", json={"title": "Cards 2"}).json()
    pid = p["id"]
    p = client.post(f"/api/storyboard/projects/{pid}/shots", json={"beat": "End", "characters": []}).json()
    base = f"/api/storyboard/projects/{pid}/shots/{p['shots'][0]['id']}"
    assert client.post(f"{base}/card").status_code == 400  # not a card yet
    assert client.patch(base, json={"kind": "poster"}).status_code == 400
    assert client.patch(base, json={"card_bg": "rainbow"}).status_code == 400
    s = client.patch(base, json={"kind": "card", "card_title": "Coming soon", "card_bg": "night"}).json()["shots"][0]
    assert (s["kind"], s["card_title"], s["card_bg"]) == ("card", "Coming soon", "night")
    assert client.post(f"{base}/card").status_code == 200


def test_script_card_lines_become_card_shots():
    r = split_script("1. Rain on the window. Mara reads.\n2. TITLE CARD: The Last Lighthouse / A short film\n"
                     "3. END CARD: Coming soon", ["Mara"])
    kinds = [(s.get("kind"), s.get("card_title"), s.get("card_sub")) for s in r["shots"]]
    assert kinds == [(None, None, None), ("card", "The Last Lighthouse", "A short film"), ("card", "Coming soon", "")]
    assert r["shots"][2]["beat"] == "End card" and r["shots"][1]["characters"] == []
    r = split_script("INT. LIGHTHOUSE - NIGHT\n\nMara reads.\n\nTITLE CARD: THE LAST LIGHTHOUSE\n\nMARA\nStay lit.", ["Mara"])
    assert [s.get("kind") for s in r["shots"]] == [None, "card"] and r["shots"][0]["line"] == "Stay lit."


def test_batch_add_keeps_cards(tmp_path):
    st = sb.Store(tmp_path / "projects")
    p = st.create_project("Batch", "Mara")
    st.add_shots(p.id, [{"beat": "Title card", "kind": "card", "card_title": "X", "characters": []}])
    s = st.load(p.id).shots[0]
    assert s.kind == "card" and s.card_title == "X"


def test_ui_has_the_card_type():
    js = (ROOT / "app/web/static/storyboard.js").read_text()
    assert 'data-kind="card"' in js and "Make the card" in js and "/card`" in js
    assert "Make the card" in (ROOT / "app/web/static/unified.js").read_text()
