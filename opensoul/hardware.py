"""Hardware-to-model picker: detect this computer, pick a tier, recommend a model per stage.

Config: presets/hardware_profiles.yaml (see docs/HARDWARE_MEMORY.md, "Hardware picker").

Detection is local and read-only: ``nvidia-smi`` (with a timeout), then ``torch.cuda`` in a child process (with a
timeout) only when nvidia-smi gave nothing, plus ``/proc/meminfo``. On macOS only, ``sysctl`` (with a timeout) reads
the Apple chip name and unified memory; a Mac still gets the fallback tier (the app has no Mac backend yet) plus a
recommendation-only tier from presets/model_manifest.yaml. Nothing here opens a network connection. The
machine count is never discovered: it comes from ``OPENSOUL_MACHINES``, else the saved setting, else 1.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "presets" / "hardware_profiles.yaml"
SMI_TIMEOUT_S = 5
TORCH_TIMEOUT_S = 10
MEMINFO = Path("/proc/meminfo")
MEASURED_SOURCE = "docs/HARDWARE_MEMORY.md"
SPARK_NAMES = re.compile(r"\bGB10\b|Grace|DGX Spark", re.I)

Runner = Callable[..., Any]


# ---------------------------------------------------------------- config

def load(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else PROFILES
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("tiers"), list):
        raise ValueError(f"hardware profiles missing a tiers list: {p}")
    return data


def license_blocked(lic: str | None, data: dict[str, Any]) -> bool:
    if not lic:
        return True
    pats = (data.get("license_rules") or {}).get("blocked_patterns") or []
    return any(re.search(p, lic, re.I) for p in pats)


def license_class(model: dict[str, Any], data: dict[str, Any]) -> str | None:
    """Which allowed class a model's licence is in: "open" (the allowlist), "ai_label" (LTX-2.x with the
    AI-generated label set), "use_restricted" (open weights with use restrictions: OpenRAIL++-M, the Llama
    Community Licence), or None (not allowed)."""
    lic = model.get("license")
    if license_blocked(lic, data):
        return None
    if lic in (data.get("license_allowlist") or []):
        return "open"
    if lic in ((data.get("license_rules") or {}).get("needs_ai_label") or []):
        return "ai_label" if model.get("ai_label") else None
    if lic in (((data.get("license_classes") or {}).get("use_restricted") or {}).get("licenses") or []):
        return "use_restricted"
    return None


def license_allowed(model: dict[str, Any], data: dict[str, Any]) -> bool:
    """In one of the allowed classes (see :func:`license_class`)."""
    return license_class(model, data) is not None


STATUSES = {"tested", "untested", "planned", "none"}


def _registry_ok(ref: dict[str, Any]) -> bool:
    f = ROOT / str(ref.get("file") or "")
    if not f.is_file():
        return False
    if f.suffix == ".json":
        ids = {m.get("id") for m in json.loads(f.read_text(encoding="utf-8")).get("models") or []}
        return ref.get("model") in ids
    stages = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("stages") or []
    for st in stages:
        if st.get("id") == ref.get("stage"):
            return any(b.get("id") == ref.get("backend") for b in st.get("backends") or [])
    return False


def problems(data: dict[str, Any] | None = None) -> list[str]:
    """Everything wrong with the profiles file ([] = valid). The tests and the API both use this."""
    data = data if data is not None else load()
    out: list[str] = []
    models = data.get("models") or {}
    stage_ids = {s.get("id") for s in data.get("stages") or []}
    for mid, m in models.items():
        if not license_allowed(m, data):
            out.append(f"model {mid}: licence {m.get('license')!r} is not allowed")
        if not isinstance(m.get("license_verified"), bool):
            out.append(f"model {mid}: license_verified must be true or false")
        if m.get("license_verified") and not m.get("license_source"):
            out.append(f"model {mid}: a verified licence needs license_source")
        if m.get("stage") not in stage_ids:
            out.append(f"model {mid}: unknown stage {m.get('stage')!r}")
        if m.get("in_app") is False:
            if m.get("registry") or not m.get("in_app_note"):
                out.append(f"model {mid}: a model not in the app has no registry entry and needs in_app_note")
        elif not _registry_ok(m.get("registry") or {}):
            out.append(f"model {mid}: registry entry {m.get('registry')} not found")
    for mid, m in (data.get("not_recommended") or {}).items():
        if mid in models:
            out.append(f"{mid} is both recommended and not recommended")
        if not m.get("reason"):
            out.append(f"not_recommended {mid}: needs a reason")
    seen: set[str] = set()
    for t in data.get("tiers") or []:
        tid = t.get("id")
        if tid in seen:
            out.append(f"tier {tid}: duplicate id")
        seen.add(tid)
        if not isinstance(t.get("tested"), bool):
            out.append(f"tier {tid}: needs tested: true or false")
        if not t.get("status_label"):
            out.append(f"tier {tid}: needs a status_label")
        status = t.get("status")
        if status not in STATUSES:
            out.append(f"tier {tid}: status must be one of {sorted(STATUSES)}")
        if (status == "tested") != bool(t.get("tested")):
            out.append(f"tier {tid}: status tested and tested: true go together")
        if status == "planned" and not t.get("planned_reason"):
            out.append(f"tier {tid}: a planned tier needs planned_reason")
        if t.get("fallback") and status != "none":
            out.append(f"tier {tid}: the fallback has status none")
        if t.get("fallback"):
            if t.get("picks"):
                out.append(f"tier {tid}: the fallback must not recommend models")
            continue
        mach = {m.get("id") for m in t.get("machines") or []}
        covered = set()
        for p in t.get("picks") or []:
            where = f"tier {tid} {p.get('stage')}"
            covered.add(p.get("stage"))
            model = models.get(p.get("model"))
            if model is None:
                out.append(f"{where}: model {p.get('model')!r} is not in models")
            elif model.get("stage") != p.get("stage"):
                out.append(f"{where}: model {p.get('model')} is a {model.get('stage')} model")
            if p.get("machine") not in mach:
                out.append(f"{where}: machine {p.get('machine')!r} is not in the tier's machines")
            if not isinstance(p.get("tested"), bool):
                out.append(f"{where}: needs tested: true or false")
            if p.get("tested") and not t.get("tested"):
                out.append(f"{where}: a pick can't be tested on an untested tier")
            mem = p.get("memory") or {}
            if "measured_gb" in mem:
                if not t.get("tested"):
                    out.append(f"{where}: measured_gb on an untested tier (use est_gb, source: estimate)")
                if not p.get("tested"):
                    out.append(f"{where}: measured_gb on an untested pick")
                if mem.get("source") != MEASURED_SOURCE:
                    out.append(f"{where}: a measured number must cite {MEASURED_SOURCE}")
                if "est_gb" in mem:
                    out.append(f"{where}: give measured_gb or est_gb, not both")
            elif "est_gb" in mem:
                if mem.get("source") != "estimate" or not mem.get("basis"):
                    out.append(f"{where}: est_gb needs source: estimate and a basis")
            else:
                out.append(f"{where}: needs memory.measured_gb or memory.est_gb")
            if not p.get("why"):
                out.append(f"{where}: needs a why line")
            if model is not None and model.get("in_app") is False:
                out.append(f"{where}: {p.get('model')} is not in the app, so it can't be a pick")
            s2 = p.get("stage2")
            if s2:
                m2 = models.get(s2.get("model"))
                if m2 is None or m2.get("stage") != p.get("stage"):
                    out.append(f"{where} stage2: model {s2.get('model')!r} is not a {p.get('stage')} model")
                if not isinstance(s2.get("tested"), bool) or not s2.get("why"):
                    out.append(f"{where} stage2: needs tested: true or false and a why line")
                if s2.get("tested") and not t.get("tested"):
                    out.append(f"{where} stage2: can't be tested on an untested tier")
                mem2 = s2.get("memory") or {}
                if "measured_gb" in mem2:
                    if not (t.get("tested") and s2.get("tested")) or mem2.get("source") != MEASURED_SOURCE:
                        out.append(f"{where} stage2: measured_gb only on a tested tier, citing {MEASURED_SOURCE}")
                elif "est_gb" not in mem2 or mem2.get("source") != "estimate" or not mem2.get("basis"):
                    out.append(f"{where} stage2: needs measured_gb or est_gb with source: estimate and a basis")
        missing = stage_ids - covered
        if missing:
            out.append(f"tier {tid}: no pick for {sorted(missing)}")
    if not any(t.get("fallback") for t in data.get("tiers") or []):
        out.append("no fallback tier")
    vo = data.get("voice_options") or {}
    opts = vo.get("options") or []
    if opts:
        ids = [o.get("model") for o in opts]
        for o in opts:
            m = models.get(o.get("model"))
            if m is None or m.get("stage") != "tts":
                out.append(f"voice option {o.get('model')!r}: not a voice model in models")
            if o.get("status") not in VOICE_STATUS:
                out.append(f"voice option {o.get('model')}: unknown status {o.get('status')!r}")
            if m is not None and (m.get("in_app") is False) != (o.get("status") == "not_in_app"):
                out.append(f"voice option {o.get('model')}: status not_in_app goes with in_app: false")
        if vo.get("app_default") not in ids or vo.get("recommended") not in ids:
            out.append("voice_options: app_default and recommended must be listed")
        if vo.get("app_default") != _registry_default("voice"):
            out.append("voice_options: app_default must match presets/models.yaml voice default_backend")
        new = [o.get("model") for o in opts if o.get("status") == "new_stories_default"]
        if new != [_new_story_default()]:
            out.append("voice_options: exactly one new_stories_default, matching presets/voice_engine.json tts_default_new")
    if sum(1 for t in data.get("tiers") or [] if t.get("tested")) != 1:
        out.append("exactly one tier may be tested (1 × Spark)")
    return out


VOICE_STATUS = {"recommended": "Recommended", "new_stories_default": "Default for new stories",
                "app_default": "Speak tab, older stories and the fallback", "in_app": "In the app",
                "not_in_app": "Not in the app yet"}


def _new_story_default() -> str | None:
    import json

    try:
        return json.loads((ROOT / "presets" / "voice_engine.json").read_text(encoding="utf-8")).get("tts_default_new")
    except (OSError, ValueError):
        return None


def _registry_default(stage_id: str) -> str | None:
    reg = yaml.safe_load((ROOT / "presets" / "models.yaml").read_text(encoding="utf-8")) or {}
    return next((s.get("default_backend") for s in reg.get("stages") or [] if s.get("id") == stage_id), None)


# ---------------------------------------------------------------- detection

def _num(s: str) -> float | None:
    try:
        return float(s.strip())
    except (TypeError, ValueError):
        return None


def parse_nvidia_smi(text: str) -> list[dict[str, Any]]:
    """`nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits` -> [{name, vram_gb}].
    Unified-memory GPUs (GB10) report memory.total as [N/A]: vram_gb None."""
    gpus = []
    for line in (text or "").splitlines():
        if not line.strip() or "," not in line:
            continue
        name, _, mem = line.rpartition(",")
        mib = _num(mem)
        gpus.append({"name": name.strip(), "vram_gb": round(mib / 1024, 2) if mib else None})
    return gpus


def parse_meminfo(text: str) -> float | None:
    """MemTotal from /proc/meminfo, in GB (GiB, as the docs report it)."""
    m = re.search(r"^MemTotal:\s+(\d+)\s*kB", text or "", re.M)
    return round(int(m.group(1)) / 1024 / 1024, 1) if m else None


def _run_smi(run: Runner) -> tuple[list[dict[str, Any]], str]:
    try:
        r = run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=SMI_TIMEOUT_S, check=False)
    except FileNotFoundError:
        return [], "nvidia-smi not found"
    except subprocess.TimeoutExpired:
        return [], f"nvidia-smi timed out after {SMI_TIMEOUT_S} s"
    except Exception as e:  # noqa: BLE001 - detection never breaks the app
        return [], f"nvidia-smi failed ({type(e).__name__})"
    if getattr(r, "returncode", 1) != 0:
        return [], "nvidia-smi returned an error"
    gpus = parse_nvidia_smi(getattr(r, "stdout", "") or "")
    return gpus, ("nvidia-smi" if gpus else "nvidia-smi listed no GPU")


_TORCH_PROBE = (
    "import json,torch\n"
    "c=torch.cuda\n"
    "print(json.dumps([{'name':c.get_device_name(i),'vram_gb':round(c.get_device_properties(i).total_memory/2**30,2)}"
    " for i in range(c.device_count())] if c.is_available() else []))"
)


def _run_torch(run: Runner) -> tuple[list[dict[str, Any]], str]:
    """torch.cuda in a child process (importing torch is slow and must never hang the app)."""
    import importlib.util

    if importlib.util.find_spec("torch") is None:
        return [], "torch not installed"
    try:
        r = run([sys.executable, "-c", _TORCH_PROBE], capture_output=True, text=True,
                timeout=TORCH_TIMEOUT_S, check=False)
        gpus = json.loads((getattr(r, "stdout", "") or "[]").strip().splitlines()[-1]) if r.returncode == 0 else []
    except Exception as e:  # noqa: BLE001
        return [], f"torch.cuda check failed ({type(e).__name__})"
    return gpus, ("torch.cuda" if gpus else "torch.cuda found no GPU")


def _read_meminfo(path: Path) -> float | None:
    try:
        return parse_meminfo(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def machines_setting(settings: dict[str, Any] | None = None, env: dict[str, str] | None = None) -> tuple[int, str]:
    """(count, where it came from). OPENSOUL_MACHINES wins, then the saved setting, then 1. Never the network."""
    env = os.environ if env is None else env
    raw = (env.get("OPENSOUL_MACHINES") or "").strip()
    if raw:
        try:
            return max(1, min(16, int(raw))), "OPENSOUL_MACHINES"
        except ValueError:
            pass
    n = (settings or {}).get("machines")
    if isinstance(n, int) and n >= 1:
        return min(16, n), "setting"
    return 1, "default"


def classify_gpu(gpus: list[dict[str, Any]]) -> dict[str, Any]:
    if not gpus:
        return {"gpu_class": "none", "unified_memory": False, "vram_gb": None, "gpu_name": None}
    spark = next((g for g in gpus if SPARK_NAMES.search(g.get("name") or "")), None)
    if spark:
        return {"gpu_class": "spark", "unified_memory": True, "vram_gb": None, "gpu_name": spark["name"]}
    best = max(gpus, key=lambda g: g.get("vram_gb") or 0)
    if best.get("vram_gb") is None:  # unknown unified-memory GPU: not one we can size
        return {"gpu_class": "unknown", "unified_memory": True, "vram_gb": None, "gpu_name": best.get("name")}
    return {"gpu_class": "discrete", "unified_memory": False, "vram_gb": best["vram_gb"], "gpu_name": best["name"]}


SYSCTL_TIMEOUT_S = 5


def _sysctl(run: Runner, key: str) -> str | None:
    try:
        r = run(["sysctl", "-n", key], capture_output=True, text=True, timeout=SYSCTL_TIMEOUT_S, check=False)
    except Exception:  # noqa: BLE001 - detection never breaks the app
        return None
    out = (getattr(r, "stdout", "") or "").strip()
    return out if getattr(r, "returncode", 1) == 0 and out else None


def detect_apple(run: Runner) -> dict[str, Any] | None:
    """macOS only: {chip, memory_gb} for Apple Silicon (sysctl, local), else None (Intel Mac or no answer)."""
    chip = _sysctl(run, "machdep.cpu.brand_string") or ""
    if not chip.startswith("Apple"):
        return None
    raw = _sysctl(run, "hw.memsize")
    mem = round(int(raw) / 2**30, 1) if raw and raw.isdigit() else None
    return {"chip": chip, "memory_gb": mem}


def detect(*, run: Runner = subprocess.run, meminfo: Path = MEMINFO, env: dict[str, str] | None = None,
           settings: dict[str, Any] | None = None, platform: str | None = None) -> dict[str, Any]:
    """What this computer has, read locally. Never raises."""
    platform = platform or sys.platform
    notes = []
    n, n_src = machines_setting(settings, env)
    if platform == "darwin":
        apple = detect_apple(run)
        if apple:
            notes.append("sysctl (Apple Silicon)")
            return {"simulated": False, "gpus": [], "memory_gb": apple["memory_gb"], "gpu_class": "none",
                    "unified_memory": True, "vram_gb": None, "gpu_name": apple["chip"], "platform": "apple",
                    "chip": apple["chip"], "machines": n, "machines_source": n_src,
                    "machine_list": list((settings or {}).get("machine_list") or [])[:16], "notes": notes}
        notes.append("sysctl found no Apple Silicon chip")
    gpus, how = _run_smi(run)
    notes.append(how)
    if not gpus:
        gpus, how = _run_torch(run)
        notes.append(how)
    mem = _read_meminfo(meminfo)
    if mem is None:
        notes.append("/proc/meminfo not readable")
    cls = classify_gpu(gpus)
    return {"simulated": False, "gpus": gpus, "memory_gb": mem, **cls,
            "platform": "cpu" if cls["gpu_class"] == "none" else "nvidia", "machines": n,
            "machines_source": n_src, "machine_list": list((settings or {}).get("machine_list") or [])[:16],
            "notes": notes}


def simulated(name: str, data: dict[str, Any] | None = None, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or load()
    sims = data.get("simulations") or {}
    if name not in sims:
        raise KeyError(name)
    s = sims[name]
    gpus = list(s.get("gpus") or [])
    out = {"simulated": True, "simulation": name, "simulation_label": s.get("label"), "gpus": gpus,
           "memory_gb": s.get("memory_gb"), **classify_gpu(gpus), "machines": int(s.get("machines") or 1),
           "machines_source": "simulation", "machine_list": list((settings or {}).get("machine_list") or [])[:16],
           "notes": ["simulated hardware (preview mode)"]}
    return out


# ---------------------------------------------------------------- recommendation

def _matches(match: dict[str, Any], hw: dict[str, Any]) -> bool:
    if not match:
        return True
    if match.get("gpu_class") and match["gpu_class"] != hw.get("gpu_class"):
        return False
    mem, vram, n = hw.get("memory_gb") or 0, hw.get("vram_gb") or 0, hw.get("machines") or 1
    if "min_memory_gb" in match and mem < match["min_memory_gb"]:
        return False
    if "min_vram_gb" in match and vram < match["min_vram_gb"]:
        return False
    if "max_vram_gb" in match and vram >= match["max_vram_gb"]:
        return False
    if "min_machines" in match and n < match["min_machines"]:
        return False
    if "max_machines" in match and n > match["max_machines"]:
        return False
    return True


def pick_tier(hw: dict[str, Any], data: dict[str, Any] | None = None) -> str:
    data = data or load()
    for t in data["tiers"]:
        if _matches(t.get("match") or {}, hw):
            return t["id"]
    return next(t["id"] for t in data["tiers"] if t.get("fallback"))


def tier_ids(data: dict[str, Any] | None = None) -> list[str]:
    return [t["id"] for t in (data or load())["tiers"]]


def describe_hardware(hw: dict[str, Any]) -> str:
    """One plain line about the computer, e.g. 'NVIDIA GB10 · 121.7 GB unified memory · 1 computer'."""
    parts = []
    if hw.get("platform") == "apple":
        parts.append(f"{hw.get('chip') or hw.get('gpu_name') or 'Apple Silicon'} · {hw.get('memory_gb') or '?'} GB "
                     "unified memory (Mac: recommendation only, the app has no Mac backend yet)")
        n = hw.get("machines") or 1
        return " · ".join(parts + [f"{n} computer" + ("s" if n != 1 else "")])
    if hw.get("gpu_class") == "none":
        parts.append("No NVIDIA graphics card found")
    elif hw.get("unified_memory"):
        parts.append(f"{hw.get('gpu_name')} · {hw.get('memory_gb') or '?'} GB shared (unified) memory")
    else:
        parts.append(f"{hw.get('gpu_name')} · {hw.get('vram_gb')} GB graphics memory")
        if hw.get("memory_gb"):
            parts.append(f"{hw['memory_gb']} GB system memory")
    if hw.get("gpu_class") == "none" and hw.get("memory_gb"):
        parts.append(f"{hw['memory_gb']} GB system memory")
    n = hw.get("machines") or 1
    parts.append(f"{n} computer" + ("s" if n != 1 else ""))
    return " · ".join(parts)


def _license_fields(m: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    cls = license_class(m, data)
    info = (data.get("license_classes") or {}).get(cls) or {}
    return {"license": m["license"], "license_class": cls, "license_class_label": info.get("label"),
            "license_class_explain": info.get("explain"), "license_verified": bool(m.get("license_verified")),
            "license_source": m.get("license_source"), "license_note": m.get("license_note"),
            "ai_label": bool(m.get("ai_label")), "url": m.get("url"),
            "weights_gb": m.get("weights_gb"), "weights_source": m.get("weights_source")}


def _badge(tested: bool, measured: bool, tier: dict[str, Any]) -> str:
    if tested and measured:
        return "tested (measured on Spark)"
    return "planned (estimate)" if tier.get("status") == "planned" else "untested (estimate)"


def _memory_fields(mem: dict[str, Any]) -> dict[str, Any]:
    measured = "measured_gb" in mem
    return {"memory_kind": "measured" if measured else "estimate",
            "measured_gb": mem.get("measured_gb") if measured else None,
            "measured_low_gb": mem.get("measured_low_gb") if measured else None,
            "est_gb": None if measured else mem.get("est_gb"),
            "memory_detail": mem.get("detail") or mem.get("basis"), "memory_source": mem.get("source")}


def _card(pick: dict[str, Any], data: dict[str, Any], tier: dict[str, Any]) -> dict[str, Any]:
    m = data["models"][pick["model"]]
    stage = next(s for s in data["stages"] if s["id"] == pick["stage"])
    mem = pick.get("memory") or {}
    measured = "measured_gb" in mem
    machine = next((x for x in tier.get("machines") or [] if x.get("id") == pick.get("machine")), {})
    card = {
        "stage": pick["stage"], "stage_label": stage["label"], "stage_plain": stage.get("plain", ""),
        "model_id": pick["model"], "model": m["label"], "precision": m.get("precision"),
        **_license_fields(m, data),
        "tested": bool(pick.get("tested")), "badge": _badge(bool(pick.get("tested")), measured, tier),
        **_memory_fields(mem),
        "machine": pick.get("machine"), "machine_label": machine.get("label"), "why": pick.get("why", ""),
        "stage2": None, "recommended": False, "app_default_note": None,
    }
    s2 = pick.get("stage2")
    if s2:
        m2 = data["models"][s2["model"]]
        mem2 = s2.get("memory") or {}
        card["stage2"] = {"model_id": s2["model"], "model": m2["label"], "precision": m2.get("precision"),
                          **_license_fields(m2, data), "tested": bool(s2.get("tested")),
                          "badge": _badge(bool(s2.get("tested")), "measured_gb" in mem2, tier),
                          **_memory_fields(mem2), "why": s2.get("why", "")}
    vo = data.get("voice_options") or {}
    if pick["stage"] == "tts" and vo:
        card["recommended"] = pick["model"] == vo.get("recommended")
        new = next((o["model"] for o in vo.get("options") or [] if o.get("status") == "new_stories_default"), None)
        if pick["model"] != new:
            nm = (data["models"].get(new) or {}).get("label", new)
            dm = (data["models"].get(vo.get("app_default")) or {}).get("label", vo.get("app_default"))
            card["app_default_note"] = (f"New stories speak with {nm} (each character's own voice clip); {dm} is the "
                                        "fallback and rollback. See Voice options below.")
    return card


def voice_options(data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    data = data or load()
    vo = data.get("voice_options") or {}
    out = []
    for o in vo.get("options") or []:
        m = data["models"][o["model"]]
        out.append({"model_id": o["model"], "model": m["label"], "status": o["status"],
                    "status_label": VOICE_STATUS.get(o["status"], o["status"]), "note": o.get("note", ""),
                    "in_app": m.get("in_app") is not False, "in_app_note": m.get("in_app_note"),
                    **_license_fields(m, data)})
    return out


def recommend(tier_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or load()
    tier = next((t for t in data["tiers"] if t["id"] == tier_id), None)
    if tier is None:
        raise KeyError(tier_id)
    order = [s["id"] for s in data["stages"]]
    picks = sorted(tier.get("picks") or [], key=lambda p: order.index(p["stage"]))
    return {
        "tier": tier["id"], "label": tier["label"], "short": tier.get("short", tier["label"]),
        "tested": bool(tier["tested"]), "status": tier.get("status"), "status_label": tier["status_label"],
        "planned_reason": tier.get("planned_reason"), "fallback": bool(tier.get("fallback")),
        "summary": tier.get("summary", ""), "note": tier.get("note"), "launch_flags": tier.get("launch_flags"),
        "machines": tier.get("machines") or [], "cards": [_card(p, data, tier) for p in picks],
        "not_recommended": [
            {"id": k, "label": v["label"], "stage": v["stage"], "license": v["license"], "reason": v["reason"],
             "license_verified": bool(v.get("license_verified")), "license_source": v.get("license_source")}
            for k, v in (data.get("not_recommended") or {}).items()],
        "voice_options": [] if tier.get("fallback") else voice_options(data),
        "license_classes": data.get("license_classes") or {},
    }


def tiers_summary(data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    data = data or load()
    return [{"id": t["id"], "label": t["label"], "short": t.get("short", t["label"]), "tested": bool(t["tested"]),
             "status": t.get("status"), "status_label": t["status_label"], "fallback": bool(t.get("fallback"))}
            for t in data["tiers"]]


# ---------------------------------------------------------------- settings (app data dir, local file)

def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / "settings" / "hardware.json"


def load_settings(data_dir: Path) -> dict[str, Any]:
    p = settings_path(data_dir)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data_dir: Path, new: dict[str, Any], data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate and store {machines, tier_override, machine_list}. Labels only: no addresses are kept or used."""
    data = data or load()
    cur = load_settings(data_dir)
    if "machines" in new:
        n = new["machines"]
        if n is None:
            cur.pop("machines", None)
        elif isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 16:
            cur["machines"] = n
        else:
            raise ValueError("the number of computers must be a whole number from 1 to 16")
    if "tier_override" in new:
        t = new["tier_override"]
        if t in (None, "", "auto"):
            cur.pop("tier_override", None)
        elif t in tier_ids(data):
            cur["tier_override"] = t
        else:
            raise ValueError(f"unknown tier {t!r}")
    if "machine_list" in new:
        items = new["machine_list"] or []
        if not isinstance(items, list) or len(items) > 16:
            raise ValueError("machine_list must be a list of up to 16 machines")
        clean = []
        for it in items:
            if not isinstance(it, dict):
                raise ValueError("each machine is an object with a label")
            label = str(it.get("label") or "").strip()[:40]
            if not label:
                raise ValueError("each machine needs a label")
            clean.append({"label": label, "role": str(it.get("role") or "")[:60]})
        cur["machine_list"] = clean
    p = settings_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")
    return cur
