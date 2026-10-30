"""opensoul/lipsync_scorer.py against a FAKE scorer CLI (a tiny Python script). The real scorer is never run."""
import json
import sys
import textwrap
from pathlib import Path

import pytest

from opensoul import lipsync as L
from opensoul import lipsync_scorer as S

ROOT = Path(__file__).resolve().parents[1]

FAKE = textwrap.dedent('''
    import json, sys, time
    args = sys.argv[1:]
    assert args[0] == "--score-only" and args[-1] == "--json", args
    video = args[1]
    ref = args[args.index("--ref") + 1] if "--ref" in args else None
    if "sleep" in video: time.sleep(5)
    if "crash" in video: print("boom: no face", file=sys.stderr); sys.exit(2)
    if "garbage" in video: print("not json at all"); sys.exit(0)
    if "nolse" in video: print(json.dumps({"lse_d": 7.0})); sys.exit(0)
    if "noface" in video: print(json.dumps({"lse_c": None, "lse_d": None, "method": "fair25"})); sys.exit(0)
    scores = {"good": 6.12, "weak": 2.97, "weak+ls": 6.64}
    name = video.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    print("loading syncnet ...")
    print(json.dumps({"lse_c": scores.get(name, 1.0), "lse_d": 7.1, "method": "fair25", "ref": ref}))
''')


@pytest.fixture
def fake(tmp_path, monkeypatch):
    cli = tmp_path / "run_lipsync_method.py"
    cli.write_text(FAKE)
    for k in (S.ENV_CLI, S.ENV_PY, S.ENV_TIMEOUT):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(S.ENV_CLI, str(cli))
    monkeypatch.setenv(S.ENV_PY, sys.executable)
    return tmp_path


def _video(d, name):
    p = d / f"{name}.mp4"
    p.write_bytes(b"\0")
    return p


def test_shipped_config_is_disabled_and_has_no_home_paths(monkeypatch):
    for k in (S.ENV_CLI, S.ENV_PY, S.ENV_TIMEOUT):
        monkeypatch.delenv(k, raising=False)
    raw = json.loads(S.CONFIG.read_text())
    assert raw["cli"] == "" and raw["python"] == "" and raw["timeout_s"] > 0
    assert "/home/" not in S.CONFIG.read_text() and "/Users/" not in S.CONFIG.read_text()
    assert not S.enabled()
    with pytest.raises(S.ScorerError) as e:
        S.score("x.mp4")
    assert e.value.code == "not_configured" and S.ENV_CLI in str(e.value)


def test_config_file_and_env_override(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"cli": "tools/score.py", "python": "", "timeout_s": 30}))
    c = S.load_config(f, env={})
    assert c.enabled and c.cli == str(ROOT / "tools/score.py") and c.timeout_s == 30
    c2 = S.load_config(f, env={S.ENV_CLI: "/opt/x/score.py", S.ENV_TIMEOUT: "5"})
    assert c2.cli == "/opt/x/score.py" and c2.timeout_s == 5
    with pytest.raises(S.ScorerError):
        S.load_config(f, env={S.ENV_TIMEOUT: "soon"})


def test_command_shape(fake):
    cmd = S.command("v.mp4", ref="raw.mp4")
    assert cmd[0] == sys.executable and cmd[1].endswith("run_lipsync_method.py")
    assert cmd[2:] == ["--score-only", "v.mp4", "--ref", "raw.mp4", "--json"]
    assert S.command("v.mp4")[2:] == ["--score-only", "v.mp4", "--json"]


def test_score_parses_the_json_after_log_lines(fake):
    r = S.score(_video(fake, "good"), ref=_video(fake, "raw"))
    assert r["lse_c"] == 6.12 and r["lse_d"] == 7.1 and r["method"] == "fair25" and r["ref"].endswith("raw.mp4")


def test_parse_output_variants():
    assert S.parse_output('log\n{"lse_c": "4.5", "lse_d": 8}\n')["lse_c"] == 4.5
    assert S.parse_output("{'lse_c': 3.0, 'method': 'fair25'}")["lse_c"] == 3.0  # python-dict print tolerated
    for bad in ("", "nothing", '{"lse_d": 1}', '{"lse_c": "n/a"}', "[1, 2]"):
        with pytest.raises(S.ScorerError) as e:
            S.parse_output(bad)
        assert e.value.code == "bad_output"


@pytest.mark.parametrize("name,code", [("crash", "failed"), ("garbage", "bad_output"), ("nolse", "bad_output")])
def test_clear_errors(fake, name, code):
    with pytest.raises(S.ScorerError) as e:
        S.score(_video(fake, name))
    assert e.value.code == code
    if code == "failed":
        assert "exit 2" in str(e.value) and "no face" in str(e.value)


def test_timeout(fake, monkeypatch):
    monkeypatch.setenv(S.ENV_TIMEOUT, "0.5")
    with pytest.raises(S.ScorerError) as e:
        S.score(_video(fake, "sleep"))
    assert e.value.code == "timeout" and "0.5 s" in str(e.value)


def test_missing_video_and_missing_cli(fake, monkeypatch):
    with pytest.raises(S.ScorerError) as e:
        S.score(fake / "nope.mp4")
    assert e.value.code == "no_video"
    monkeypatch.setenv(S.ENV_CLI, str(fake / "gone.py"))
    with pytest.raises(S.ScorerError) as e:
        S.score(_video(fake, "good"))
    assert e.value.code == "missing"


def test_scorer_drives_run_rebuilt_method_end_to_end(fake):
    raw = _video(fake, "raw")
    _video(fake, "weak+ls")

    def latentsync(take):
        return str(Path(take).with_name(Path(take).stem + "+ls.mp4"))

    out = L.run_rebuilt_method(str(_video(fake, "weak")), run_latentsync=latentsync,
                               run_inner_mouth=lambda t: t + "#im", ref=raw)
    assert out["fallback_ran"] and out["method"] == "latentsync" and out["lse_c"] == 6.64
    assert out["take"].endswith("weak+ls.mp4#im") and out["lse_c_artic"] == 2.97
    good = L.run_rebuilt_method(str(_video(fake, "good")), run_latentsync=latentsync, run_inner_mouth=lambda t: t)
    assert not good["fallback_ran"] and good["lse_c"] == 6.12


def test_null_lse_c_is_a_no_face_scorer_failure(fake):
    with pytest.raises(S.ScorerError) as e:
        S.parse_output('{"lse_c": null, "lse_d": null, "method": "fair25"}')
    assert e.value.code == "no_face"
    with pytest.raises(S.ScorerError) as e:
        S.score(_video(fake, "noface"))
    assert e.value.code == "no_face"


def test_null_lse_c_keeps_the_a2v_take_flagged_without_latentsync(fake):
    ran = []
    out = L.run_rebuilt_method(str(_video(fake, "noface")), run_latentsync=lambda t: ran.append(t) or t + "+ls",
                               run_inner_mouth=lambda t: t + "#im", ref=_video(fake, "raw"))
    assert ran == []                                          # no automatic LatentSync fallback
    assert out["take"].endswith("noface.mp4#im") and out["method"] == L.REBUILT_METHOD
    assert out["scorer_failed"] and out["flag"].startswith("no_face") and not out["fallback_ran"]
    assert out["lse_c"] is None and out["lse_c_artic"] is None
