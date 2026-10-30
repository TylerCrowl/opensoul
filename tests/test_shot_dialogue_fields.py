"""Per-shot dialogue on the model + API: line (allowed tags only), speaker from the cast, voice override, lip-sync."""
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    import app.server as server

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


def _story(c, **shot):
    p = c.post("/api/storyboard/projects", json={"title": "Diner", "shots": [{"beat": "Counter", "characters": ["Lumi", "Bram"], **shot}]})
    assert p.status_code == 200, p.text
    return p.json()


def test_line_speaker_voice_round_trip_and_defaults(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    p = _story(c)
    s = p["shots"][0]
    assert (s["line"], s["speaker"], s["voice"], s["lipsync"], s["lipsync_backend"], s["face_box"]) == ("", "", "", True, "ltx_av", None)
    u = f"/api/storyboard/projects/{p['id']}/shots/{s['id']}"
    s = c.patch(u, json={"line": "Whole milk. (chuckles)  Obviously.", "speaker": "lumi", "voice": "Tara",
                         "lipsync_backend": "latentsync", "face_box": [300, 200, 180, 220]}).json()["shots"][0]
    assert s["line"] == "Whole milk. <chuckle> Obviously." and s["speaker"] == "Lumi" and s["voice"] == "tara"
    assert s["lipsync_backend"] == "latentsync" and s["face_box"] == [300, 200, 180, 220]
    s = c.patch(u, json={"prompt": "rain outside"}).json()["shots"][0]
    assert s["line"].startswith("Whole milk") and s["speaker"] == "Lumi"  # untouched by other edits
    s = c.patch(u, json={"voice": "", "face_box": []}).json()["shots"][0]
    assert s["voice"] == "" and s["face_box"] is None


def test_bad_values_are_400_and_save_nothing(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    p = _story(c, line="Hi.")
    u = f"/api/storyboard/projects/{p['id']}/shots/{p['shots'][0]['id']}"
    for bad in ({"line": "Hi <scream>"}, {"speaker": "Nobody"}, {"voice": "robot"}, {"lipsync_backend": "wav2lip"},
                {"face_box": [1, 2, 0, 4]}, {"line": "x" * 501}):
        r = c.patch(u, json=bad)
        assert r.status_code == 400, bad
    assert c.get(f"/api/storyboard/projects/{p['id']}").json()["shots"][0]["line"] == "Hi."
    r = c.post("/api/storyboard/projects", json={"title": "Bad", "shots": [{"beat": "A", "line": "<shout> no"}]})
    assert r.status_code == 400 and "<laugh>" in r.json()["detail"]


def test_cast_change_drops_a_speaker_who_left(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    p = _story(c, line="Order up.", speaker="Bram")
    u = f"/api/storyboard/projects/{p['id']}/shots/{p['shots'][0]['id']}"
    s = c.patch(u, json={"characters": ["Lumi"]}).json()["shots"][0]
    assert s["speaker"] == "" and s["line"] == "Order up."
    assert c.patch(u, json={"characters": ["Lumi", "Bram"], "speaker": "Bram"}).json()["shots"][0]["speaker"] == "Bram"


def test_script_split_keeps_line_and_speaker_into_the_story(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post("/api/storyboard/script/split", json={"text": "INT. BUS STOP - NIGHT\nKai waits.\nKAI\nCome on (sighs), come on.\n"}).json()
    row = r["shots"][0]
    assert row["line"] and row["speaker"] == "Kai"
    p = c.post("/api/storyboard/projects", json={"title": "Bus", "shots": [row]}).json()
    s = p["shots"][0]
    assert s["line"] == "Come on <sigh>, come on." and s["speaker"] == "Kai"
    single = c.post(f"/api/storyboard/projects/{p['id']}/shots", json={"beat": "B", "characters": ["Kai"], "line": "Late again.", "speaker": "Kai"}).json()
    assert single["shots"][-1]["speaker"] == "Kai"


def test_old_project_files_load_with_dialogue_defaults(tmp_path):
    import json

    from opensoul import storyboard as sb

    st = sb.Store(tmp_path)
    p = st.create_project("Old")
    st.add_shot(p.id, "A")
    f = tmp_path / p.id / "project.json"
    d = json.loads(f.read_text())
    for k in sb.DIALOGUE_FIELDS:
        d["shots"][0].pop(k, None)
    f.write_text(json.dumps(d))
    s = st.load(p.id).shots[0]
    assert s.line == "" and s.lipsync is True and s.lipsync_backend == "ltx_av"
