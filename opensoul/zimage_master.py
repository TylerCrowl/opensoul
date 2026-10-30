"""Text-only master on Z-Image-Turbo (Tongyi-MAI/Z-Image-Turbo, Apache-2.0), workflow 07z.

One original-character portrait from the user's words (no photo of anyone), drawn by a ComfyUI over its native API:
``POST /prompt`` -> poll ``GET /history/{prompt_id}`` -> fetch the image with ``GET /view``. Cancelling uses
``opensoul.comfy_cancel.cancel_own_prompt`` (our prompt only, never someone else's).

Model files are plain names under ComfyUI's ``models/`` folders (presets/text_master.json); nothing here knows a
machine path. Env overrides: OPENSOUL_ZIMAGE_UNET, OPENSOUL_ZIMAGE_CLIP, OPENSOUL_ZIMAGE_VAE, OPENSOUL_MASTER_BACKEND
(zimage | qwen07t), OPENSOUL_COMFYUI_URL (default http://127.0.0.1:8188).

Standard library only, so a studio-side runner can load this file by path without the rest of the package."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "presets" / "text_master.json"
WORKFLOW = "workflows/07z_master_from_text_zimage_api.json"
BACKENDS = ("zimage", "qwen07t")
DEFAULT_URL = "http://127.0.0.1:8188"
N_UNET, N_CLIP, N_VAE, N_SHIFT, N_POS, N_NEG, N_LATENT, N_SAMPLER, N_SAVE = "1", "2", "3", "4", "5", "6", "7", "8", "10"

HttpFn = Callable[[str, str, Optional[dict]], Any]
FetchFn = Callable[[str], bytes]


class MasterCancelled(RuntimeError):
    pass


def load_config(path: str | Path | None = None, env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    p = Path(path) if path else CONFIG
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    files = dict(cfg.get("files") or {})
    for key, var in (("unet", "OPENSOUL_ZIMAGE_UNET"), ("clip", "OPENSOUL_ZIMAGE_CLIP"), ("vae", "OPENSOUL_ZIMAGE_VAE")):
        if env.get(var):
            files[key] = env[var]
    cfg["files"] = files
    b = (env.get("OPENSOUL_MASTER_BACKEND") or cfg.get("backend") or "zimage").strip().lower()
    cfg["backend"] = b if b in BACKENDS else "zimage"
    cfg["comfyui_url"] = (env.get("OPENSOUL_COMFYUI_URL") or cfg.get("comfyui_url") or DEFAULT_URL).rstrip("/")
    return cfg


# 07z is a distilled turbo model: it runs at cfg 1, where the negative prompt is never evaluated. Pinned here so a
# preset edit can't turn guidance on; the positive prompt carries everything (opensoul.text_master.master_parts).
CFG_PIN = 1.0
PROMPT_DEFAULTS = {"outfit_line": "", "expression": "Serious calm face, mouth relaxed and closed at the corners",
                   "hair": ", both ears clearly visible"}  # = text_master.NEUTRAL / EARS_SEEN


def master_prompt(description: str, cfg: dict, **parts: str) -> str:
    """The 07z prompt: the preset template with the description and the text_master.master_parts() pieces."""
    tmpl = cfg.get("prompt") or "Photorealistic reference photo of {description}."
    vals = {**PROMPT_DEFAULTS, **{k: v for k, v in parts.items() if v is not None},
            "description": description.strip().rstrip(".")}
    return re.sub(r"\s{2,}", " ", tmpl.format_map(vals)).strip()


def build_graph(prompt: str, seed: int, cfg: dict, *, negative: str | None = None, prefix: str = "opensoul/master",
                workflow: dict | None = None) -> dict:
    """Workflow 07z with this master's prompt, seed, size and model files filled in."""
    g = copy.deepcopy(workflow if workflow is not None else json.loads((ROOT / WORKFLOW).read_text(encoding="utf-8")))
    f, s = cfg.get("files") or {}, cfg.get("sampler") or {}
    if f.get("unet"):
        g[N_UNET]["inputs"]["unet_name"] = f["unet"]
    if f.get("clip"):
        g[N_CLIP]["inputs"]["clip_name"] = f["clip"]
    if f.get("clip_type"):
        g[N_CLIP]["inputs"]["type"] = f["clip_type"]
    if f.get("vae"):
        g[N_VAE]["inputs"]["vae_name"] = f["vae"]
    if "shift" in s:
        g[N_SHIFT]["inputs"]["shift"] = float(s["shift"])
    g[N_POS]["inputs"]["text"] = prompt
    g[N_NEG]["inputs"]["text"] = negative if negative is not None else cfg.get("negative", "")
    g[N_LATENT]["inputs"].update(width=int(cfg.get("width", 1024)), height=int(cfg.get("height", 1536)), batch_size=1)
    ks = g[N_SAMPLER]["inputs"]
    ks["seed"] = int(seed)
    for k, cast in (("steps", int), ("sampler_name", str), ("scheduler", str)):
        if k in s:
            ks[k] = cast(s[k])
    ks["cfg"] = CFG_PIN  # never from the preset (see CFG_PIN)
    g[N_SAVE]["inputs"]["filename_prefix"] = prefix
    return g


def _http(method: str, url: str, body: Optional[dict] = None, timeout: float = 30) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {}, method=method)
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    return json.loads(raw) if raw else None


def _fetch(url: str) -> bytes:
    return urllib.request.urlopen(url, timeout=120).read()


def _cancel_fn():
    try:
        from opensoul.comfy_cancel import cancel_own_prompt
        return cancel_own_prompt
    except ImportError:  # loaded by path on the studio computer
        spec = importlib.util.spec_from_file_location("comfy_cancel", Path(__file__).with_name("comfy_cancel.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.cancel_own_prompt


def run(prompt: str, seed: int, out_path: str | Path, *, cfg: dict | None = None, negative: str | None = None,
        base_url: str | None = None, http: HttpFn | None = None, fetch: FetchFn | None = None,
        on_prompt_id: Callable[[str], None] | None = None, should_cancel: Callable[[], bool] | None = None,
        poll_s: float = 1.0, timeout_s: float | None = None, sleep: Callable[[float], None] = time.sleep,
        client_id: str = "opensoul-master") -> Path:
    """Queue one master, wait for it, save the picture at ``out_path``. Raises MasterCancelled or RuntimeError."""
    cfg = cfg if cfg is not None else load_config()
    base = (base_url or cfg.get("comfyui_url") or DEFAULT_URL).rstrip("/")
    http, fetch = http or _http, fetch or _fetch
    graph = build_graph(prompt, seed, cfg, negative=negative)
    r = http("POST", f"{base}/prompt", {"prompt": graph, "client_id": client_id}) or {}
    pid = r.get("prompt_id")
    if not pid:
        raise RuntimeError(f"ComfyUI did not accept the master: {str(r.get('error') or r)[:300]}")
    if on_prompt_id:
        on_prompt_id(pid)
    limit = float(timeout_s or cfg.get("timeout_s") or 900)
    t0 = time.monotonic()
    while True:
        if should_cancel and should_cancel():
            _cancel_fn()(base, pid)
            raise MasterCancelled(pid)
        try:
            h = (http("GET", f"{base}/history/{pid}", None) or {}).get(pid)
        except (urllib.error.URLError, OSError, TimeoutError) as e:  # OS-025: a short drop; the studio keeps going
            if time.monotonic() - t0 > limit:
                raise RuntimeError("Lost the studio connection. Check the studio and the network. Then try again.") from e
            sleep(max(poll_s, 3.0))
            continue
        if h:
            st = h.get("status") or {}
            if st.get("status_str") == "error":
                msgs = [m for m in st.get("messages", []) if m and m[0] == "execution_error"]
                raise RuntimeError("The master failed in the studio"
                                   + (f": {msgs[-1][1].get('exception_message', '')[:300]}" if msgs else "."))
            imgs = ((h.get("outputs") or {}).get(N_SAVE) or {}).get("images") or []
            if imgs:
                im = imgs[0]
                q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                                            "type": im.get("type", "output")})
                out = Path(out_path)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(fetch(f"{base}/view?{q}"))
                return out
            if st.get("completed"):
                raise RuntimeError("The master finished without a picture.")
        if time.monotonic() - t0 > limit:
            _cancel_fn()(base, pid)
            raise RuntimeError("The master took too long, so OpenSoul cancelled it.")
        sleep(poll_s)
