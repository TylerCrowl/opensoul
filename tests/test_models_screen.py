"""Models screen: GET /api/hardware/models (slots + fit badges for this or a simulated computer), the approve command
the plan route shows. The page itself: tests/test_models_screen_ui.py."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opensoul import model_manifest as MM
from opensoul import setup_engine as SE

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "web" / "static"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import hardware_routes as routes
    from app import server

    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.delenv("OPENSOUL_MACHINES", raising=False)
    monkeypatch.setattr(server, "DATA", tmp_path)
    routes._cache.clear()
    yield TestClient(server.app)
    routes._cache.clear()


# ---------------------------------------------------------------- fit logic

def _m(platforms, est=None, tiers=()):
    return {"platforms": platforms, "memory": {"est_gb": est, "source": "estimate"} if est is not None else None,
            "memory_by_tier": [{"tier": t, "gb": g, "kind": k} for t, g, k in tiers]}


def test_fit_by_platform_and_memory():
    rtx = {"platform": "nvidia", "gpu_class": "discrete", "vram_gb": 24.0, "memory_gb": 64}
    assert MM.fit(_m(["nvidia"], 8), rtx)["status"] == "fits"
    assert MM.fit(_m(["nvidia"], 23), rtx)["status"] == "tight"
    assert MM.fit(_m(["nvidia"], 40), rtx)["status"] == "too_big"
    assert MM.fit(_m(["apple"], 8), rtx)["status"] == "wrong_platform"
    assert MM.fit(_m(["nvidia"]), rtx)["status"] == "unknown"
    mac = {"platform": "apple", "gpu_class": "none", "memory_gb": 64.0}
    f = MM.fit(_m(["apple"], 40), mac)
    assert f["status"] == "fits" and f["budget_gb"] == 48.0  # three quarters of unified memory
    assert MM.fit(_m(["apple"], 47), mac)["status"] == "tight"


def test_memory_need_prefers_the_computers_tier_then_the_smallest():
    m = _m(["nvidia"], tiers=[("spark_x1", 70.7, "measured"), ("rtx_24gb", 24, "estimate")])
    assert MM.memory_need(m, "spark_x1") == (70.7, "measured")
    assert MM.memory_need(m, "fallback") == (24.0, "estimate")
    assert MM.memory_need(_m(["nvidia"], 8)) == (8.0, "estimate")


# ---------------------------------------------------------------- API

def test_models_route_has_every_slot_with_active_first_and_fit(client):
    d = client.get("/api/hardware/models?simulate=spark").json()
    assert [s["id"] for s in d["slots"]] == list(MM.SLOT_IDS)
    by = {s["id"]: s for s in d["slots"]}
    assert by["voice"]["active"] == "voxcpm2" and by["lipsync"]["active"] == "ltx_av"  # defaults unchanged
    for s in d["slots"]:
        assert s["options"][0]["is_active"] and s["options"][0]["id"] == s["active"]
        for o in s["options"]:
            assert o["fit"]["status"] in {"fits", "tight", "too_big", "wrong_platform", "unknown"}
            for k in ("license", "commercial_use", "platforms", "weights_gb", "in_app", "installed"):
                assert k in o, k
    ltx = next(o for o in by["video"]["options"] if o["id"] == "ltx25_bf16")
    assert ltx["fit"]["status"] == "fits" and ltx["fit"]["need_kind"] == "measured"
    assert d["tier"] == "spark_x1" and d["hardware"]["simulated"]


def test_models_route_follows_preview_as_mac(client):
    d = client.get("/api/hardware/models?simulate=mac64").json()
    by = {s["id"]: {o["id"]: o for o in s["options"]} for s in d["slots"]}
    assert by["video"]["ltx25_int8"]["fit"]["status"] == "wrong_platform"
    assert by["video"]["ltx25_mlx_q4"]["fit"]["status"] == "fits"
    assert by["voice"]["kokoro_mlx"]["fit"]["status"] == "fits"
    assert {s["id"] for s in d["simulations"]} >= {"spark", "mac64", "rtx4060"}


def test_models_route_commercial_filter_and_errors(client, monkeypatch):
    d = client.get("/api/hardware/models?commercial=open_only&simulate=spark").json()
    for s in d["slots"]:
        assert all(o["commercial_use"] == "yes" for o in s["options"])
    by = {s["id"]: s for s in d["slots"]}
    assert by["video"]["hidden_count"] >= 2 and by["image"]["hidden_count"] == 0
    assert client.get("/api/hardware/models?commercial=free").status_code == 400
    assert client.get("/api/hardware/models?simulate=nope").status_code == 404
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "0")
    assert client.get("/api/hardware/models?simulate=spark").status_code == 400


def test_models_route_shows_a_saved_swap_as_active(client, tmp_path):
    SE._write_slots(tmp_path, {"active": {"voice": "kokoro"}, "history": []})
    by = {s["id"]: s for s in client.get("/api/hardware/models?simulate=spark").json()["slots"]}
    assert by["voice"]["active"] == "kokoro" and by["voice"]["active_source"] == "saved"
    assert by["voice"]["options"][0]["id"] == "kokoro" and by["voice"]["default"] == "voxcpm2"


def test_plan_route_shows_the_users_approve_command_and_approves_nothing(client, tmp_path):
    p = client.post("/api/setup/plan", json={"models": ["latentsync"], "slot_changes": {"lipsync": "latentsync"}}).json()
    assert p["ok"] and p["dry_run"] and p["slot_changes"] == [{"slot": "lipsync", "from": "ltx_av", "to": "latentsync"}]
    cmd = p["approve_command"]
    assert cmd.startswith("python -m opensoul.setup_engine --data ") and str(tmp_path.resolve()) in cmd
    assert cmd.endswith(f"approve {p['plan_id']} --accept-licenses")  # LatentSync needs a licence yes
    rec = SE._load_plan(tmp_path, p["plan_id"])
    assert rec["approval"] is None  # a plan, never an approval
    assert not SE.slots_path(tmp_path).exists()
    bad = client.post("/api/setup/plan", json={"models": ["ltx25_mlx_q4"]}).json()
    assert not bad["ok"] and "approve_command" not in bad
    assert not [r for r in client.app.routes if "approve" in getattr(r, "path", "")]


def test_approve_command_runs_the_cli_approve(tmp_path, capsys):
    plan = SE.plan_install(["kokoro"], {"voice": "kokoro"}, data_dir=tmp_path)
    cmd = SE.approve_command(plan, tmp_path)
    assert "--accept-licenses" not in cmd  # Apache-2.0: no licence yes needed
    argv = cmd.split()[3:]  # drop "python -m opensoul.setup_engine"
    assert SE.main(argv) == 0 and "approval_token" in capsys.readouterr().out
    assert SE.approve_command(plan, SE.ROOT / "data") == f"python -m opensoul.setup_engine approve {plan['plan_id']}"
