"""opensoul/setup_engine.py: plan -> approve -> apply, dry run first. Nothing real is downloaded or run: the executor is
a fake, model folders are temp dirs, and preview mode only reports."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from opensoul import setup_engine as SE

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSOUL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("COMFY_DIR", str(tmp_path / "home" / "ComfyUI"))
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    return tmp_path / "data"


class FakeRun:
    def __init__(self, code=0):
        self.calls, self.code = [], code

    def __call__(self, argv, **kw):
        assert isinstance(argv, list) and "shell" not in kw  # never a shell string
        self.calls.append((argv, kw.get("env", {}), kw.get("cwd")))
        return type("R", (), {"returncode": self.code})()


def test_plan_is_a_dry_run_that_lists_groups_disk_and_licences(env):
    p = SE.plan_install(["ltx25_bf16", "kokoro"], data_dir=env)
    assert p["ok"] and p["dry_run"] and p["kind"] == "install" and re.fullmatch(r"[0-9a-f]{16}", p["plan_id"])
    by = {i["model"]: i for i in p["items"]}
    assert by["ltx25_bf16"]["commands"][0]["argv"] == ["bash", "scripts/download_models.sh", "video"]
    assert by["ltx25_bf16"]["commands"][0]["env"] == {"LTX_VARIANT": "bf16"}
    assert by["kokoro"]["commands"][0]["env"] == {"ALLOW_PICKLE": "1"}
    assert p["download_gb_upper_bound"] == pytest.approx(71.2 + 0.33)
    assert p["license_acks_needed"] == ["ltx25_bf16"] and p["gated_downloads"] == ["ltx25_bf16"]
    assert isinstance(p["disk_fits"], bool) or p["disk_fits"] is None
    saved = list((env / "setup" / "plans").glob("*.json"))
    assert [f.stem for f in saved] == [p["plan_id"]]
    assert not (env / "settings" / "slots.json").exists()  # a plan changes no slot


def test_plan_refuses_candidates_blocked_and_filtered_models(env):
    p = SE.plan_install(["seedvr2_3b", "flux2_dev", "arcface", "nope"], data_dir=env)
    assert not p["ok"] and len(p["errors"]) == 4 and not (env / "setup" / "plans").exists()
    assert any("not in the app yet" in e for e in p["errors"])
    assert sum("blocked licence" in e for e in p["errors"]) == 2
    p = SE.plan_install(["ltx25_int8"], commercial="open_only", data_dir=env)
    assert not p["ok"] and "outside the 'open_only' filter" in p["errors"][0]
    with pytest.raises(SE.SetupError):
        SE.plan_install([], data_dir=env)


def test_installed_models_need_no_download(env):
    from opensoul import model_manifest as MM
    from opensoul import models_registry as MR

    for f in MM.resolve("kokoro")["files"]:
        q = MR._resolve_path(f)
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_bytes(b"x")
    p = SE.plan_install(["kokoro"], data_dir=env)
    assert p["items"][0]["installed"] is True and p["items"][0]["commands"] == [] and p["download_gb_upper_bound"] == 0


def test_apply_needs_flag_token_and_licence_yes(env):
    p = SE.plan_install(["ltx25_bf16"], data_dir=env)
    run = FakeRun()
    with pytest.raises(SE.SetupError, match="approve flag"):
        SE.apply_install(p["plan_id"], "x", data_dir=env, executor=run, dry_run=False)
    with pytest.raises(SE.SetupError, match="no unused approval"):
        SE.apply_install(p["plan_id"], "x", approve_flag=True, data_dir=env, executor=run, dry_run=False)
    with pytest.raises(SE.SetupError, match="accept-licenses"):
        SE.approve(p["plan_id"], data_dir=env)
    tok = SE.approve(p["plan_id"], data_dir=env, accept_licenses=True)["approval_token"]
    with pytest.raises(SE.SetupError, match="does not match"):
        SE.apply_install(p["plan_id"], "wrong", approve_flag=True, data_dir=env, executor=run, dry_run=False)
    assert run.calls == []
    rec = json.loads((env / "setup" / "plans" / f"{p['plan_id']}.json").read_text())
    assert tok not in json.dumps(rec)  # only the hash is stored


def test_preview_mode_apply_reports_and_runs_nothing(env):
    p = SE.plan_install(["kokoro"], data_dir=env)
    tok = SE.approve(p["plan_id"], data_dir=env)["approval_token"]
    run = FakeRun()
    out = SE.apply_install(p["plan_id"], tok, approve_flag=True, data_dir=env, executor=run)  # OPENSOUL_DRY_RUN=1
    assert out["executed"] is False and out["would_run"][0]["argv"][1] == "scripts/download_models.sh"
    assert run.calls == []


def test_apply_runs_the_plans_commands_once_with_a_fake_executor(env):
    p = SE.plan_install(["kokoro"], {"voice": "kokoro"}, data_dir=env)
    tok = SE.approve(p["plan_id"], data_dir=env)["approval_token"]
    run = FakeRun()
    out = SE.apply_install(p["plan_id"], tok, approve_flag=True, data_dir=env, executor=run, dry_run=False)
    assert out["ok"] and [c[0] for c in run.calls] == [["bash", "scripts/download_models.sh", "tts"]]
    assert run.calls[0][1]["ALLOW_PICKLE"] == "1" and run.calls[0][2] == str(ROOT)
    assert SE.active_slots(env) == {"voice": "kokoro"}
    with pytest.raises(SE.SetupError, match="no unused approval"):  # a token works once
        SE.apply_install(p["plan_id"], tok, approve_flag=True, data_dir=env, executor=run, dry_run=False)
    log = [json.loads(x) for x in (env / "setup" / "log.jsonl").read_text().splitlines()]
    assert [e["event"] for e in log] == ["plan", "approve", "apply_cmd", "slots"]
    assert SE.rollback(data_dir=env)["slots"] == {} and SE.active_slots(env) == {}


def test_a_failed_command_stops_and_changes_no_slot(env):
    p = SE.plan_install(["kokoro"], {"voice": "kokoro"}, data_dir=env)
    tok = SE.approve(p["plan_id"], data_dir=env)["approval_token"]
    out = SE.apply_install(p["plan_id"], tok, approve_flag=True, data_dir=env, executor=FakeRun(1), dry_run=False)
    assert out["ok"] is False and SE.active_slots(env) == {}


def test_expired_or_edited_plans_are_refused(env, monkeypatch):
    p = SE.plan_install(["kokoro"], data_dir=env)
    tok = SE.approve(p["plan_id"], data_dir=env)["approval_token"]
    f = env / "setup" / "plans" / f"{p['plan_id']}.json"
    rec = json.loads(f.read_text())
    rec["body"]["models"][0]["commands"][0]["argv"] = ["bash", "-c", "echo edited"]
    f.write_text(json.dumps(rec))
    with pytest.raises(SE.SetupError, match="changed after the user approved it"):
        SE.apply_install(p["plan_id"], tok, approve_flag=True, data_dir=env, executor=FakeRun(), dry_run=False)
    p = SE.plan_install(["orpheus"], data_dir=env)
    tok = SE.approve(p["plan_id"], data_dir=env, accept_licenses=True)["approval_token"]
    monkeypatch.setattr(time, "time", lambda: 1e12)
    with pytest.raises(SE.SetupError, match="expired"):
        SE.apply_install(p["plan_id"], tok, approve_flag=True, data_dir=env, executor=FakeRun(), dry_run=False)


def test_set_slot_plans_then_records_and_rolls_back(env):
    plan = SE.set_slot("voice", "kokoro", data_dir=env)
    assert plan["ok"] and plan["slot_changes"] == [{"slot": "voice", "from": "voxcpm2", "to": "kokoro"}]
    assert SE.active_slots(env) == {}  # planning changes nothing
    tok = SE.approve(plan["plan_id"], data_dir=env)["approval_token"]
    out = SE.set_slot("voice", "kokoro", tok, plan["plan_id"], data_dir=env)  # preview mode: install not required
    assert out["slots"] == {"voice": "kokoro"} and "does not read the slot file yet" in out["note"]
    assert SE.rollback(data_dir=env)["slots"] == {}
    with pytest.raises(SE.SetupError, match="nothing to roll back"):
        SE.rollback(data_dir=env)
    bad = SE.set_slot("voice", "ltx25_int8", data_dir=env)
    assert not bad["ok"] and "not a voice model" in bad["errors"][0]


def test_set_slot_outside_preview_needs_the_model_installed(env, monkeypatch):
    plan = SE.set_slot("voice", "chatterbox", data_dir=env)
    tok = SE.approve(plan["plan_id"], data_dir=env)["approval_token"]
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "0")
    with pytest.raises(SE.SetupError, match="not installed"):
        SE.set_slot("voice", "chatterbox", tok, plan["plan_id"], data_dir=env)


def test_health_is_local_and_reports_missing_files(env):
    h = SE.health(env)
    assert h["problems"] == {"model_manifest": [], "hardware_profiles": []}
    assert any(m["stage"] == "video" for m in h["missing"]) and h["ok"] is False
    assert h["dry_run"] is True


def test_bad_plan_ids_are_rejected(env):
    for pid in ("../../etc", "", "ABCDEF0123456789"):
        with pytest.raises(SE.SetupError):
            SE.approve(pid, data_dir=env)


def test_cli_plan_and_apply_flag(env, capsys):
    assert SE.main(["--data", str(env), "plan", "--model", "kokoro"]) == 0
    pid = json.loads(capsys.readouterr().out)["plan_id"]
    assert SE.main(["--data", str(env), "apply", pid, "--token", "t"]) == 2  # no --approve
    assert "approve flag" in capsys.readouterr().err


def test_engine_source_has_no_network_or_shell():
    src = (ROOT / "opensoul/setup_engine.py").read_text()
    for mod in ("socket", "urllib", "requests", "httpx", "http.client"):
        assert not re.search(rf"^\s*(import|from)\s+{re.escape(mod)}\b", src, re.M), mod
    assert "shell=True" not in src and "sudo" not in src.replace("no sudo", "")
