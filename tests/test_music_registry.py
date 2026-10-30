"""presets/music_models.json: swappable song / stem / beat models; nothing unconfirmed can be switched on."""
import copy
import json
import re
from pathlib import Path

import pytest

from opensoul.music import registry as R
from opensoul.music import song as SONG
from opensoul.music import stems as STEMS

ROOT = Path(__file__).resolve().parents[1]


def test_registry_is_valid_and_has_the_chosen_models():
    data = R.load()
    assert R.problems(data) == []
    ids = {m["id"] for m in data["models"]}
    assert {"ace_step", "heartmula", "beat_this", "opensoul_onset", "preview_tone", "preview_stem"} <= ids
    # rejected by the licence check: never listed
    assert not ids & {"yue", "songbloom", "diffrhythm", "musicgen"}


def test_licences_come_from_the_report_and_unconfirmed_models_carry_none():
    data = R.load()
    by = {m["id"]: m for m in data["models"]}
    assert by["ace_step"]["license"] == "MIT" and by["heartmula"]["license"] == "Apache-2.0" and by["beat_this"]["license"] == "MIT"
    assert by["ace_step"]["revision"]["comfy_files"].endswith("6707deb277e9e0907fd9c14ce6b6f1d695c6a3fc")
    for m in data["models"]:
        if m["status"] not in ("confirmed", "blocked"):
            assert m["license"] is None and not m["enabled"], m["id"]
        if m["status"] == "blocked":
            assert not m["enabled"] and R.is_blocked(m, data), m["id"]
        if R.usable(m, data):
            assert m["license"] in R.allowed_licenses(data) and m["confirmed_by"], m["id"]
    for mid in ("ace_step", "heartmula"):
        assert by[mid]["gpu_validated"] is False  # never run from the app on the GPU yet


def test_studio_default_is_ace_step_and_preview_entries_stay_in_preview():
    studio, preview = R.choices("song"), R.choices("song", preview=True)
    assert studio["default"] == "ace_step" and preview["default"] == "preview_tone"
    assert not any(o["preview"] for o in studio["options"])
    assert any(p["id"] == "heartmula" for p in studio["pending"])  # listed as "not ready", never offered
    assert R.choices("stems")["options"] == [] and R.choices("stems")["empty_reason"]
    assert [o["id"] for o in R.choices("stems", preview=True)["options"]] == ["preview_stem"]


def test_switching_on_a_model_without_a_confirmed_licence_is_an_error():
    data = copy.deepcopy(R.load())
    m = next(x for x in data["models"] if x["id"] == "demucs")
    m.update(id="some_splitter", status="unconfirmed", license=None, license_url="https://example.org", enabled=True)
    assert any(p.startswith("some_splitter: enabled but") for p in R.problems(data))
    m.update(status="confirmed", license="CC-BY-NC-4.0", confirmed_by="x", vram_gb=4, max_seconds=600, vocals=True,
             lyrics_input=False, prompt_input=False, runner={"kind": "runner", "module": "x"})
    assert any("is blocked" in p for p in R.problems(data))
    m["license"] = "MIT"
    assert R.problems(data) == ["some_splitter: enabled but no pinned revision (a git sha after @, or a sha256)"]
    m["revision"] = "example/stem-model@" + "0" * 40
    assert R.problems(data) == []
    hm = next(x for x in data["models"] if x["id"] == "heartmula")
    hm["enabled"] = True
    assert any("heartmula: enabled but no ComfyUI workflow" in p for p in R.problems(data))


def test_unknown_fields_and_bad_ids_are_caught(tmp_path):
    data = copy.deepcopy(R.load())
    data["models"].append({**data["models"][0], "id": "Bad-Id", "speed": 3})
    probs = R.problems(data)
    assert any("lower_snake_case" in p for p in probs) and any("unknown fields speed" in p for p in probs)


ACE_GRAPH = {  # same node ids / types / inputs as the production song workflow (ComfyUI core nodes)
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "acestep_v1.5_xl_turbo_bf16.safetensors", "weight_dtype": "default"}},
    "5": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {"tags": "", "lyrics": "", "seed": 0, "bpm": 118, "duration": 140.0,
                                                                "timesignature": "4", "language": "en", "keyscale": "A minor"}},
    "7": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": 140.0, "batch_size": 1}},
    "8": {"class_type": "KSampler", "inputs": {"seed": 0, "steps": 8}},
    "10": {"class_type": "SaveAudio", "inputs": {"audio": ["9", 0], "filename_prefix": "x"}},
}


def test_ace_step_runner_nodes_name_real_inputs_of_the_song_workflow():
    m = R.get("ace_step")
    nodes = m["runner"]["nodes"]
    for key, target in nodes.items():
        if key == "output":
            assert ACE_GRAPH[target]["class_type"] == "SaveAudio"
        else:
            assert target[1] in ACE_GRAPH[target[0]]["inputs"], key
    ins = SONG.song_inputs(m, lyrics="[Verse]\nla la", style="pop, 112 BPM", seconds=30, seed=5)
    assert ins["5"]["lyrics"].startswith("[Verse]") and ins["5"]["bpm"] == 112 and ins["7"]["seconds"] == 30.0
    assert ins["8"]["seed"] == 5 and ins["5"]["duration"] == 30.0


def test_song_workflow_runs_through_the_sdk_path_with_overrides(tmp_path, monkeypatch):
    wf = tmp_path / "song_api.json"
    wf.write_text(json.dumps(ACE_GRAPH))
    monkeypatch.setenv("OPENSOUL_ACE_STEP_WORKFLOW", str(wf))
    seen = {}

    def fake_run(path, *, inputs, output_node_id, out_dir):
        from opensoul.comfy_client import apply_inputs, load_graph

        apply_inputs(load_graph(path), inputs)  # the same typo check the real run does
        seen.update(path=path, inputs=inputs, out=output_node_id)
        f = Path(out_dir) / "song_00001.flac"
        f.write_bytes(b"x")
        return [f]

    out = SONG.run_song_workflow(R.get("ace_step"), tmp_path, lyrics="hey", style="", seconds=20, seed=1, run=fake_run)
    assert out.name == "song_00001.flac" and seen["out"] == "10" and seen["inputs"]["5"]["lyrics"] == "hey"


def test_editor_format_workflows_are_refused(tmp_path, monkeypatch):
    wf = tmp_path / "tpl.json"
    wf.write_text(json.dumps({"nodes": [], "links": []}))
    monkeypatch.setenv("OPENSOUL_ACE_STEP_WORKFLOW", str(wf))
    with pytest.raises(SONG.SongError, match="Export \\(API\\)"):
        SONG.run_song_workflow(R.get("ace_step"), tmp_path, lyrics="", style="", seconds=20, seed=1, run=lambda *a, **k: [])


def test_the_shipped_song_workflow_exists_and_matches_the_node_map():
    m = R.get("ace_step")
    wf = ROOT / m["runner"]["workflow"]
    assert wf.is_file() and R.workflow_file(m) == wf
    graph = json.loads(wf.read_text())
    assert SONG.is_api_format(graph)
    for key, target in m["runner"]["nodes"].items():
        if key == "output":
            assert graph[target]["class_type"] == "SaveAudio"
        else:
            assert target[1] in graph[target[0]]["inputs"], key
    assert {n["class_type"] for n in ACE_GRAPH.values()} <= {graph[k]["class_type"] for k in graph}
    loaders = [v for n in graph.values() for v in n["inputs"].values() if isinstance(v, str) and v.endswith(".safetensors")]
    assert sorted(loaders) == sorted(Path(f).name for f in m["files"])


def test_a_missing_workflow_file_makes_the_model_unavailable(monkeypatch):
    data = copy.deepcopy(R.load())
    m = next(x for x in data["models"] if x["id"] == "ace_step")
    m["runner"]["workflow"] = "workflows/does_not_exist_api.json"
    assert R.why_not_usable(m, data) == ["workflow file workflows/does_not_exist_api.json is missing"]
    assert any("ace_step: enabled but workflow file" in p for p in R.problems(data))
    assert "ace_step" not in [o["id"] for o in _choices(data, "song")]
    monkeypatch.setenv("OPENSOUL_ACE_STEP_WORKFLOW", "/nonexistent/song_api.json")
    assert R.why_not_usable(R.get("ace_step"), R.load()) == ["workflow file song_api.json is missing"]


def _choices(data, role, tmp=None):
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "m.json"
        p.write_text(json.dumps(data))
        return R.choices(role, p)["options"]


def test_an_enabled_third_party_model_must_have_a_pinned_revision():
    data = R.load()
    for m in data["models"]:
        if m["enabled"] and not R.own_code(m):
            assert R.pinned(m["revision"]), m["id"]
    for bad in (None, "", "main", {"model": "HeartMuLa/HeartMuLa-oss-3B@main"}, {}, "abc123",
                {"a": "x@" + "0" * 40, "b": None}):
        d = copy.deepcopy(data)
        m = next(x for x in d["models"] if x["id"] == "ace_step")
        m["revision"] = bad
        assert "no pinned revision (a git sha after @, or a sha256)" in R.why_not_usable(m, d), bad
        assert any(p.startswith("ace_step: enabled but") for p in R.problems(d))
    assert R.pinned("x@" + "a" * 40) and R.pinned("b" * 64) and not R.pinned("x@" + "A" * 39)


def test_heartmula_is_pinned_to_the_apache_revisions():
    h = R.get("heartmula")
    assert h["revision"] == {"model": "HeartMuLa/HeartMuLa-oss-3B-happy-new-year@41f6fc68490e11dc43fdabaa6b5767946408c903",
                             "codec": "HeartMuLa/HeartCodec-oss-20260123@f889dab0532cfa4bf459f2a3367eb6d346b8eeda"}
    assert R.pinned(h["revision"]) and not h["enabled"]


def test_download_groups_named_in_the_registry_exist_and_are_pinned():
    import re

    sh = (ROOT / "scripts" / "download_models.sh").read_text()
    groups = set(re.search(r"stills\|sheet\|[a-z|]+\)", sh).group(0).rstrip(")").split("|"))
    for m in R.load()["models"]:
        if m.get("download_group"):
            assert m["download_group"] in groups, m["id"]
            assert re.search(rf"^{m['download_group']}\(\) {{", sh, re.M), m["id"]
    body = sh[sh.index("music() {"):sh.index("\n}", sh.index("music() {"))]
    assert "/resolve/6707deb277e9e0907fd9c14ce6b6f1d695c6a3fc/" in body
    fetches = re.findall(r'fetch "\$A/(\S+)" "\$M/(\S+)" ([0-9a-f]{64})$', body, re.M)
    assert sorted(f[1] for f in fetches) == sorted(R.get("ace_step")["files"])
    assert {f[2][:8] for f in fetches} == {"86a1afb0", "fd4590c8", "ffe5ffb8", "6de92e3a"}
    assert "music" not in sh[sh.index("SEL=(stills"):].splitlines()[0]  # not in the default set


def test_shipped_music_files_cite_only_shipped_docs():
    files = [*ROOT.glob("opensoul/music/*.py"), ROOT / "app/music_routes.py", ROOT / "presets/music_models.json",
             ROOT / "app/web/static/music.js", ROOT / "docs/MUSIC.md", *ROOT.glob("workflows/08m_*")]
    for f in files:
        s = f.read_text()
        assert "review/" not in s and "MUSIC_TAB_PLAN" not in s and "MUSIC_MODELS_REPORT" not in s, f.name
        low = s.lower()
        assert not [w for w in ("/workspace", "/home/", "model scout", "content ceo", "contest submission", "shot auditor",
                                "the owner", "minimax", "suno") if w in low], f.name
        assert not re.search(r"\budio\b", low), f.name
    assert "Do not name real artists or songs" in (ROOT / "app/web/static/music.js").read_text()


def test_every_enabled_model_has_a_contest_ok_licence():
    data = R.load()
    assert data["license_allowlist"] == ["Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0", "CC-BY-4.0"]
    for m in data["models"]:
        if m["enabled"]:
            assert m["license"] in R.allowed_licenses(data) and R.license_problem(m, data) == "", m["id"]
            assert R.pinned(m["revision"]) or R.own_code(m), m["id"]
    assert R.undecided() == []


@pytest.mark.parametrize("lic,why", [
    ("CC-BY-NC-4.0", "blocked"), ("CC-BY-NC-SA-4.0", "blocked"), ("Research-only licence", "blocked"),
    ("Gated, no redistribution", "blocked"), ("Some Custom Licence 1.0", "undecided"), ("ISC", "undecided"),
    ("CC-BY-4.0", "needs a credit line"), ("LTX-2 Community License", "needs the AI-generated label")])
def test_licence_policy(lic, why):
    data = copy.deepcopy(R.load())
    m = next(x for x in data["models"] if x["id"] == "ace_step")
    m.update(license=lic, credit=None)
    assert why in R.license_problem(m, data)
    assert any(p.startswith("ace_step: enabled but") for p in R.problems(data))
    if why == "needs a credit line":
        m["credit"] = "Music by an example model, CC BY 4.0"
        assert R.license_problem(m, data) == ""
    if why == "needs the AI-generated label":
        m["ai_label"] = True
        assert R.license_problem(m, data) == ""
    if why == "undecided":
        p = ROOT / "presets" / "music_models.json"
        tmp = Path(__import__("tempfile").mkdtemp()) / "m.json"
        tmp.write_text(json.dumps(data))
        assert {"id": "ace_step", "license": lic} in R.undecided(tmp) and p.is_file()


def test_no_stem_separation_by_default_and_the_ui_says_so():
    from opensoul.music import stems as STEMS

    data = R.load()
    by = {m["id"]: m for m in data["models"]}
    ex = by["ace_step_extract"]
    assert data["defaults"]["stems"] == "ace_step_extract" and ex["enabled"] is False and ex["gpu_validated"] is False
    assert ex["revision"]["xl_base"] == "ACE-Step/acestep-v15-xl-base@220c1166efbdd9583eafcb12eb160594bbfcb241"
    assert ex["license"] == "MIT" and ex["download_group"] == "music" and ex["runner"]["stub"] is True
    st = STEMS.status(False)
    assert st["available"] is False
    assert st["note"] == "Syncing to the full song (this studio has no vocal-only track)."
    assert STEMS.status(True)["available"] and "hum" in STEMS.status(True)["note"]
    with pytest.raises(RuntimeError, match="full song"):
        STEMS.extract_vocals(Path("song.wav"), Path("."))
    from opensoul.music import ace_extract

    with pytest.raises(NotImplementedError):
        ace_extract.extract_vocals(Path("song.wav"), Path("."))
    sh = (ROOT / "scripts" / "download_models.sh").read_text()
    body = sh[sh.index("music() {"):sh.index("\n}", sh.index("music() {"))]
    assert 'if [[ "${ACE_XL_BASE:-0}" != 1 ]]' in body and "--revision \"$xrev\"" in body
    assert "xrev=220c1166efbdd9583eafcb12eb160594bbfcb241" in body and body.count(".safetensors:") == 4


def test_demucs_is_blocked_never_offered_and_can_never_be_enabled():
    data = copy.deepcopy(R.load())
    d = next(m for m in data["models"] if m["id"] == "demucs")
    assert d["status"] == "blocked" and d["license"] == "research-only (weights)" and not d["enabled"]
    assert not d["credit"] and not d["download_group"]
    assert R.is_blocked(d, data)
    stems = R.choices("stems")
    assert "demucs" not in [o["id"] for o in stems["options"]] + [p["id"] for p in stems["pending"]]
    # even with every other field filled in, a blocked entry can't be switched on
    d.update(enabled=True, confirmed_by="x", vram_gb=4, max_seconds=600, vocals=True, lyrics_input=False, prompt_input=False,
             runner={"kind": "runner", "module": "x"}, revision="x@" + "0" * 40)
    assert any(p.startswith("demucs: enabled but blocked") for p in R.problems(data))
    d["status"] = "confirmed"
    assert any(p.startswith("demucs: enabled but license research-only (weights) is blocked") for p in R.problems(data))


def test_music_tab_is_full_studio_only():
    js = (ROOT / "app/web/static/music.js").read_text()
    assert 'get("ui") === "classic") { btn.remove(); view.remove(); return; }' in js
    html = (ROOT / "app/web/index.html").read_text()
    nav = html[html.index('id="ufTools"'):html.index("</nav>", html.index('id="ufTools"'))]
    assert 'id="ufMusicBtn"' in nav and "shell-full" in html[html.index('id="ufTools"') - 60:html.index('id="ufTools"')]  # Tools: full studio only
    assert html.count('id="ufMusicBtn"') == 1



def test_stems_role_says_full_mix_by_default_and_stem_only_with_xl_base():
    data = json.loads((ROOT / "presets/music_models.json").read_text())
    role = data["roles"]["stems"]
    assert "full mix by default" in role and "XL base" in role and "runs on the vocal stem" not in role
    js = (ROOT / "app/web/static/music.js").read_text()
    assert 'id="muStemNote"' in js and "the full song drives the mouth" in js  # the note sits next to the Sync buttons
