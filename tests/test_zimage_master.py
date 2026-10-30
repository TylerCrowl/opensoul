"""Text-only master on Z-Image-Turbo (workflow 07z) against a fake ComfyUI: no GPU, no model files."""
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from PIL import Image

from opensoul import zimage_master as zm

ROOT = Path(__file__).resolve().parents[1]
PNG = io.BytesIO()
Image.new("RGB", (8, 12), (120, 90, 60)).save(PNG, "PNG")
PNG = PNG.getvalue()
STOP = "/inter" + "rupt"  # ComfyUI's stop endpoint (only opensoul/comfy_cancel.py may call it)


class FakeComfy:
    """POST /prompt, GET /history/{id} (empty for the first `wait` polls), GET /view, plus /queue and the stop endpoint."""

    def __init__(self, wait=1, fail=False):
        self.posted, self.views, self.deleted, self.interrupted, self.polls = [], [], [], [], 0
        self.wait, self.fail, self.running = wait, fail, True
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj, raw=None):
                body = raw if raw is not None else json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/prompt":
                    outer.posted.append(body)
                    return self._send({"prompt_id": "pid-1", "number": 1})
                if self.path == "/queue":
                    outer.deleted += body.get("delete", [])
                    return self._send({})
                if self.path == STOP:
                    outer.interrupted.append(body)
                    return self._send({})
                self._send({})

            def do_GET(self):
                if self.path.startswith("/history/"):
                    outer.polls += 1
                    if outer.polls <= outer.wait:
                        return self._send({})
                    if outer.fail:
                        return self._send({"pid-1": {"status": {"status_str": "error", "completed": False, "messages": [
                            ["execution_error", {"exception_message": "out of memory"}]]}, "outputs": {}}})
                    outer.running = False
                    return self._send({"pid-1": {"status": {"status_str": "success", "completed": True}, "outputs": {
                        "10": {"images": [{"filename": "master_00001_.png", "subfolder": "opensoul", "type": "output"}]}}}})
                if self.path.startswith("/view?"):
                    outer.views.append(self.path)
                    return self._send(None, PNG)
                if self.path == "/queue":
                    return self._send({"queue_running": [[0, "pid-1"]] if outer.running else [], "queue_pending": []})
                self._send({})

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def comfy():
    f = FakeComfy()
    yield f
    f.close()


def test_config_names_files_not_machine_paths_and_env_overrides(monkeypatch):
    cfg = zm.load_config(env={})
    assert cfg["backend"] == "zimage" and cfg["comfyui_url"] == zm.DEFAULT_URL
    assert cfg["files"] == {"unet": "z_image_turbo_bf16.safetensors", "clip": "qwen_3_4b.safetensors",
                            "clip_type": "lumina2", "vae": "ae.safetensors"}
    assert cfg["model"] == {"name": "Z-Image-Turbo", "repo": "Tongyi-MAI/Z-Image-Turbo", "license": "Apache-2.0"}
    raw = (ROOT / "presets/text_master.json").read_text()
    assert "/home/" not in raw and "~/" not in raw and "/Users/" not in raw
    env = {"OPENSOUL_ZIMAGE_UNET": "my_zimage.safetensors", "OPENSOUL_ZIMAGE_CLIP": "te.safetensors",
           "OPENSOUL_ZIMAGE_VAE": "v.safetensors", "OPENSOUL_MASTER_BACKEND": "QWEN07T", "OPENSOUL_COMFYUI_URL": "http://x:1/"}
    c2 = zm.load_config(env=env)
    assert c2["files"]["unet"] == "my_zimage.safetensors" and c2["files"]["vae"] == "v.safetensors"
    assert c2["backend"] == "qwen07t" and c2["comfyui_url"] == "http://x:1"
    assert zm.load_config(env={"OPENSOUL_MASTER_BACKEND": "something"})["backend"] == "zimage"


def test_graph_is_the_z_image_turbo_recipe_with_allowlisted_core_nodes():
    cfg = zm.load_config(env={})
    g = zm.build_graph("a portrait", 42, cfg)
    assert g["1"]["class_type"] == "UNETLoader" and g["1"]["inputs"]["unet_name"] == "z_image_turbo_bf16.safetensors"
    assert g["2"]["inputs"] == {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"}
    assert g["3"]["inputs"]["vae_name"] == "ae.safetensors" and g["4"]["inputs"]["shift"] == 3.0
    ks = g["8"]["inputs"]
    assert (ks["seed"], ks["steps"], ks["cfg"], ks["sampler_name"], ks["scheduler"]) == (42, 9, 1.0, "res_multistep", "simple")
    assert g["5"]["inputs"]["text"] == "a portrait" and "watermark" in g["6"]["inputs"]["text"]
    assert (g["7"]["inputs"]["width"], g["7"]["inputs"]["height"]) == (1024, 1536)
    allowed = json.loads((ROOT / "workflows/node_allowlist.json").read_text())
    core = set(allowed.get("comfy_core", []))
    assert {n["class_type"] for n in g.values()} <= core
    assert zm.master_prompt("a tall courier.", cfg).startswith("Photorealistic three-quarter-length reference photo of a tall courier.")


def test_run_queues_one_prompt_polls_history_and_saves_the_picture(comfy, tmp_path):
    seen = []
    out = zm.run("a portrait", 5, tmp_path / "m" / "master.png", cfg=zm.load_config(env={}), base_url=comfy.url,
                 on_prompt_id=seen.append, poll_s=0.01)
    assert out.read_bytes() == PNG and seen == ["pid-1"] and len(comfy.posted) == 1
    assert comfy.posted[0]["prompt"]["8"]["inputs"]["seed"] == 5 and comfy.polls >= 2
    assert "filename=master_00001_.png" in comfy.views[0] and "subfolder=opensoul" in comfy.views[0]


def test_a_comfy_error_is_a_plain_message(tmp_path):
    f = FakeComfy(wait=0, fail=True)
    try:
        with pytest.raises(RuntimeError, match="out of memory"):
            zm.run("x", 1, tmp_path / "m.png", cfg=zm.load_config(env={}), base_url=f.url, poll_s=0.01)
    finally:
        f.close()


def test_cancel_only_ever_cancels_our_own_prompt(comfy, tmp_path):
    comfy.wait = 10_000
    with pytest.raises(zm.MasterCancelled):
        zm.run("x", 1, tmp_path / "m.png", cfg=zm.load_config(env={}), base_url=comfy.url, poll_s=0.01,
               should_cancel=lambda: comfy.polls >= 2)
    # ours was the running prompt: comfy_cancel stops it by our prompt id (never a bare stop)
    assert comfy.interrupted == [{"prompt_id": "pid-1"}] and not (tmp_path / "m.png").exists()
    assert STOP not in (ROOT / "opensoul/zimage_master.py").read_text()


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSOUL_DRY_RUN", "1")
    monkeypatch.setenv("OPENSOUL_SHEET_SYNC", "1")
    import app.server as server
    from fastapi.testclient import TestClient

    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "LIBRARY", tmp_path / "library")
    return TestClient(server.app)


LOOK = {"name": "Tamsin", "look": "a lanky lighthouse keeper with a grey braid", "outfit": "a mustard oilskin coat",
        "age": "36-50", "style": "natural"}


def test_studio_master_runs_workflow_07z_on_the_fake_comfyui_and_saves_with_its_origin(client, comfy, monkeypatch):
    import app.server as server

    monkeypatch.setattr(server, "_dry", lambda: False)
    monkeypatch.setenv("OPENSOUL_COMFYUI_URL", comfy.url)
    monkeypatch.delenv("OPENSOUL_MASTER_BACKEND", raising=False)
    m = client.post("/api/master", data={**LOOK, "seed": "33"}).json()
    assert m["state"] == "done" and m["backend"] == "zimage" and m["model"] == "Z-Image-Turbo", m
    sent = comfy.posted[0]["prompt"]
    assert sent["8"]["inputs"]["seed"] == 33 and sent["5"]["inputs"]["text"] == m["prompt"]
    assert "wearing a mustard oilskin coat" in m["prompt"] and m["prompt_lock"] != m["prompt"]  # the 07z prompt (master_parts)
    monkeypatch.setattr(server, "_dry", lambda: True)
    assert client.get(m["url"]).content == PNG
    s = client.post(f"/api/master/{m['master_id']}/save", data={"name": "Tamsin"}).json()
    o = json.loads((Path(s["pack_dir"]) / "pack.json").read_text())["meta"]["origin"]
    assert o["kind"] == "text" and o["workflow"] == zm.WORKFLOW and o["seed"] == 33


def test_master_is_a_background_job_that_can_be_stopped(client, monkeypatch):
    monkeypatch.delenv("OPENSOUL_SHEET_SYNC")
    monkeypatch.setenv("OPENSOUL_MASTER_PREVIEW_DELAY", "5")
    m = client.post("/api/master", data={**LOOK, "seed": "3"}).json()
    assert m["state"] in ("queued", "running") and m["url"] is None and not m["done"]
    assert client.post(f"/api/master/{m['master_id']}/save").status_code == 404  # nothing to save yet
    c = client.post(f"/api/master/{m['master_id']}/cancel").json()
    assert c["stage"] in ("Stopping…", "Stopped.")
    for _ in range(50):
        st = client.get(f"/api/master/{m['master_id']}").json()
        if st["done"]:
            break
        time.sleep(0.05)
    assert st["state"] == "cancelled" and st["url"] is None
    assert client.get("/api/master/0123456789").status_code == 404
    assert client.post("/api/master/0123456789/cancel").status_code == 404


def test_docs_name_the_model_and_its_license_and_the_downloader_pins_it():
    for rel in ("README.md", "docs/MODEL_STACK.md", "workflows/README.md"):
        s = (ROOT / rel).read_text()
        assert "Z-Image-Turbo" in s and "Apache-2.0" in s, rel
    dl = (ROOT / "scripts/download_models.sh").read_text()
    for sha in ("2407613050b809ffdff18a4ac99af83ea6b95443ecebdf80e064a79c825574a6",
                "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a",
                "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38"):
        assert sha in dl
    assert "master()" in dl and "Comfy-Org/z_image_turbo" in dl
