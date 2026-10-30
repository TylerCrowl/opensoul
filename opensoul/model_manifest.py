"""Model manifest: one swappable model slot per pipeline step (image, edit, video, lipsync, music, voice, upscale).

Data: presets/model_manifest.yaml (docs/SETUP.md). Models the app runs today take their facts (licence, licence source,
download size, URL) from presets/hardware_profiles.yaml and their files from presets/models.yaml, so nothing is copied
twice; candidates not in the app yet carry their own facts. Everything here is local and read-only: file reads and
file-existence checks, no network.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from opensoul import hardware as HW

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "presets" / "model_manifest.yaml"
SLOT_IDS = ("image", "edit", "video", "lipsync", "music", "voice", "upscale")
PLATFORMS = {"nvidia", "apple", "cpu"}
MEMORY_SOURCES = {"estimate", "reported"}
COMMERCIAL = {"open": "yes", "ai_label": "conditional", "use_restricted": "conditional"}
COMMERCIAL_FILTERS = ("any", "allowed", "open_only")
FACT_KEYS = ("label", "license", "license_verified", "license_source", "license_note", "ai_label", "url",
             "weights_gb", "weights_source")


# ---------------------------------------------------------------- loading

def load(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else MANIFEST
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("slots"), list) or not isinstance(data.get("models"), dict):
        raise ValueError(f"model manifest needs a slots list and a models map: {p}")
    return data


@lru_cache(maxsize=1)
def _models_yaml() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "presets" / "models.yaml").read_text(encoding="utf-8")) or {}


def _music_json() -> dict[str, Any]:
    return json.loads((ROOT / "presets" / "music_models.json").read_text(encoding="utf-8"))


def _voice_engine() -> dict[str, Any]:
    return json.loads((ROOT / "presets" / "voice_engine.json").read_text(encoding="utf-8"))


def _registry_stage(stage_id: str | None) -> dict[str, Any] | None:
    return next((s for s in _models_yaml().get("stages") or [] if s.get("id") == stage_id), None)


def _registry_backend(model_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for st in _models_yaml().get("stages") or []:
        for b in st.get("backends") or []:
            if b.get("id") == model_id:
                return st, b
    return None


def app_default(slot: dict[str, Any]) -> str | None:
    """The model the app itself uses for this slot today (read from the app's own presets, never from the manifest)."""
    sid = slot.get("id")
    if sid == "voice":
        return _voice_engine().get("tts_default_new")
    if sid == "music":
        return (_music_json().get("defaults") or {}).get("song")
    if sid == "upscale":
        return "ltx_spatial_upscaler_x2"
    st = _registry_stage(slot.get("app_stage"))
    return st.get("default_backend") if st else None


# ---------------------------------------------------------------- resolved view

def _memory_by_tier(model_id: str, hw_data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for t in hw_data.get("tiers") or []:
        for p in t.get("picks") or []:
            for pick in (p, p.get("stage2")):
                if pick and pick.get("model") == model_id:
                    mem = pick.get("memory") or {}
                    out.append({"tier": t["id"], "kind": "measured" if "measured_gb" in mem else "estimate",
                                "gb": mem.get("measured_gb", mem.get("est_gb")), "source": mem.get("source")})
    return out


def resolve(mid: str, data: dict[str, Any] | None = None, hw_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """One model with every fact the picker and the installer need, wherever the fact lives."""
    data = data or load()
    hw_data = hw_data or HW.load()
    m = data["models"][mid]
    if m.get("in_app") and "own" not in m:
        facts = {k: (hw_data.get("models") or {}).get(mid, {}).get(k) for k in FACT_KEYS}
        facts["facts_from"] = "presets/hardware_profiles.yaml"
        mem_tiers = _memory_by_tier(mid, hw_data)
        memory = m.get("memory")  # only for in-app models no picker tier names (e.g. Z-Image-Turbo)
    else:
        src = m.get("own") or m
        facts = {k: src.get(k) for k in FACT_KEYS}
        facts["facts_from"] = "presets/model_manifest.yaml"
        mem_tiers = []
        memory = src.get("memory")
    cls = HW.license_class({"license": facts.get("license"), "ai_label": facts.get("ai_label")}, hw_data)
    info = (hw_data.get("license_classes") or {}).get(cls) or {}
    reg = _registry_backend(mid)
    music = next((x for x in _music_json().get("models") or [] if x.get("id") == mid), None)
    if reg:
        files = list(reg[1].get("files") or [])
    elif music:
        files = list(music.get("files") or [])
    else:
        files = [m["own"]["file"]] if (m.get("own") or {}).get("file") else []
    return {
        "id": mid, "slot": m.get("slot"), "also_slots": list(m.get("also_slots") or []), **facts,
        "license_class": cls, "license_class_label": info.get("label"), "commercial_use": COMMERCIAL.get(cls, "no"),
        "in_app": bool(m.get("in_app")), "in_app_note": m.get("in_app_note"), "optional": bool(m.get("optional")),
        "runtime": m.get("runtime", "comfyui"), "platforms": list(m.get("platforms") or []),
        "bundled_with": list(m.get("bundled_with") or []), "memory": memory, "memory_by_tier": mem_tiers,
        "install": m.get("install"), "files": files,
    }


def commercial_ok(model: dict[str, Any], mode: str = "any") -> bool:
    """``any``: every allowed model; ``allowed``: commercial use allowed (yes or conditional); ``open_only``: yes only."""
    if mode not in COMMERCIAL_FILTERS:
        raise ValueError(f"commercial filter must be one of {COMMERCIAL_FILTERS}")
    cu = model.get("commercial_use")
    return {"any": cu != "no", "allowed": cu in ("yes", "conditional"), "open_only": cu == "yes"}[mode]


def installed(model: dict[str, Any]) -> bool | None:
    """True / False from local file checks for models the app runs; None when OpenSoul can't tell (not in the app)."""
    if not model.get("in_app"):
        return None
    from opensoul import models_registry as MR

    files = model.get("files") or []
    if not files and model.get("bundled_with"):
        return None
    return all(MR._resolve_path(f).is_file() for f in files) if files else None


def slots(commercial: str = "any", data: dict[str, Any] | None = None, hw_data: dict[str, Any] | None = None,
          check_files: bool = True, active: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Every slot with its app default, the active model (a saved swap or the default) and the ranked options."""
    data = data or load()
    hw_data = hw_data or HW.load()
    out = []
    for s in data["slots"]:
        opts = []
        for mid, m in data["models"].items():
            if m.get("slot") != s["id"] and s["id"] not in (m.get("also_slots") or []):
                continue
            r = resolve(mid, data, hw_data)
            if not commercial_ok(r, commercial):
                continue
            if check_files:
                r["installed"] = installed(r)
            opts.append(r)
        opts.sort(key=lambda r: (r["id"] != s.get("default"), not r["in_app"], r["id"]))
        chosen = (active or {}).get(s["id"])
        out.append({"id": s["id"], "label": s["label"], "plain": s.get("plain", ""), "default": s.get("default"),
                    "fallback": s.get("fallback"), "active": chosen or s.get("default"),
                    "active_source": "saved" if chosen else "app default", "options": opts,
                    "blocked": [b for b in blocked(data, hw_data) if b.get("slot") == s["id"]]})
    return out


def blocked(data: dict[str, Any] | None = None, hw_data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    data = data or load()
    hw_data = hw_data or HW.load()
    out = []
    for bid, b in (data.get("blocked") or {}).items():
        src = (hw_data.get("not_recommended") or {}).get(bid, {}) if b.get("ref") == "hardware_profiles" else b
        out.append({"id": bid, "slot": b.get("slot"), "label": src.get("label"), "license": src.get("license"),
                    "license_source": src.get("license_source"), "reason": src.get("reason")})
    return out


# ---------------------------------------------------------------- validation

def problems(data: dict[str, Any] | None = None, hw_data: dict[str, Any] | None = None) -> list[str]:
    """Everything wrong with the manifest ([] = valid). Tests and the setup API both use this."""
    data = data if data is not None else load()
    hw_data = hw_data or HW.load()
    out: list[str] = []
    ids = [s.get("id") for s in data.get("slots") or []]
    if tuple(ids) != SLOT_IDS:
        out.append(f"slots must be {list(SLOT_IDS)} in that order, got {ids}")
    models = data.get("models") or {}
    for s in data.get("slots") or []:
        d = s.get("default")
        if d not in models:
            out.append(f"slot {s.get('id')}: default {d!r} is not in models")
        elif not models[d].get("in_app"):
            out.append(f"slot {s.get('id')}: the default must be a model the app runs")
        if d != app_default(s):
            out.append(f"slot {s.get('id')}: default {d!r} differs from the app's own default {app_default(s)!r}")
        if s.get("app_stage") and _registry_stage(s["app_stage"]) is None:
            out.append(f"slot {s.get('id')}: app_stage {s['app_stage']!r} is not a presets/models.yaml stage")
        if s.get("picker_stage") and s["picker_stage"] not in {st.get("id") for st in hw_data.get("stages") or []}:
            out.append(f"slot {s.get('id')}: picker_stage {s['picker_stage']!r} is not a hardware_profiles stage")
    voice = next((s for s in data.get("slots") or [] if s.get("id") == "voice"), {})
    vreg = _registry_stage("voice") or {}
    if voice.get("fallback") != vreg.get("default_backend"):
        out.append("slot voice: fallback must be presets/models.yaml voice default_backend")
    for mid, m in models.items():
        where = f"model {mid}"
        if m.get("slot") not in SLOT_IDS:
            out.append(f"{where}: unknown slot {m.get('slot')!r}")
        for extra in m.get("also_slots") or []:
            if extra not in SLOT_IDS:
                out.append(f"{where}: unknown also_slot {extra!r}")
        if not set(m.get("platforms") or []) or not set(m.get("platforms") or []) <= PLATFORMS:
            out.append(f"{where}: platforms must be a non-empty subset of {sorted(PLATFORMS)}")
        for b in m.get("bundled_with") or []:
            if b not in models:
                out.append(f"{where}: bundled_with {b!r} is not in models")
        if not isinstance(m.get("in_app"), bool):
            out.append(f"{where}: in_app must be true or false")
            continue
        if m["in_app"]:
            if "own" not in m:
                if mid not in (hw_data.get("models") or {}):
                    out.append(f"{where}: an in-app model needs an entry in presets/hardware_profiles.yaml models")
                for k in FACT_KEYS:
                    if k in m:
                        out.append(f"{where}: {k} is read from hardware_profiles.yaml; don't copy it here")
            in_music = any(x.get("id") == mid for x in _music_json().get("models") or [])
            if _registry_backend(mid) is None and not in_music and "own" not in m:
                out.append(f"{where}: not a backend in presets/models.yaml or a model in presets/music_models.json")
            inst = m.get("install") or {}
            if not inst:
                out.append(f"{where}: an in-app model needs install (download_groups or setup)")
            for g in inst.get("download_groups") or []:
                if g not in download_groups():
                    out.append(f"{where}: download group {g!r} is not in scripts/download_models.sh")
            if inst.get("setup") and not (ROOT / inst["setup"]).is_file():
                out.append(f"{where}: setup script {inst['setup']} not found")
            mem = m.get("memory") or {}
            if mem and ("measured_gb" in mem or mem.get("source") not in MEMORY_SOURCES or not mem.get("basis")):
                out.append(f"{where}: memory here is an estimate (source estimate|reported, a basis, no measured_gb)")
            own = m.get("own")
            if own:
                out.extend(_fact_problems(where, own, hw_data))
                if own.get("file") and not any(own["file"] in (_registry_backend(b) or ({}, {}))[1].get("files", [])
                                               for b in m.get("bundled_with") or []):
                    out.append(f"{where}: own.file must be one of its bundled_with backend's files")
        else:
            if m.get("install") is not None:
                out.append(f"{where}: a model not in the app has install: null (OpenSoul can't install it yet)")
            if not m.get("in_app_note"):
                out.append(f"{where}: needs in_app_note (why it isn't in the app yet)")
            out.extend(_fact_problems(where, m, hw_data))
    out.extend(advisory_problems(data))
    for bid, b in (data.get("blocked") or {}).items():
        if bid in models:
            out.append(f"blocked {bid}: also listed as a model")
        if b.get("ref") == "hardware_profiles":
            if bid not in (hw_data.get("not_recommended") or {}):
                out.append(f"blocked {bid}: not in hardware_profiles.yaml not_recommended")
        else:
            if HW.license_allowed({"license": b.get("license")}, hw_data):
                out.append(f"blocked {bid}: its licence is allowed, so it should not be blocked")
            if not b.get("reason") or not b.get("license_source"):
                out.append(f"blocked {bid}: needs a reason and a license_source")
    return out


def _fact_problems(where: str, m: dict[str, Any], hw_data: dict[str, Any]) -> list[str]:
    import re

    out = []
    for k in ("label", "license", "license_source", "url", "weights_source"):
        if not m.get(k):
            out.append(f"{where}: needs {k}")
    if not HW.license_allowed({"license": m.get("license"), "ai_label": m.get("ai_label")}, hw_data):
        out.append(f"{where}: licence {m.get('license')!r} is not in an allowed class")
    if not isinstance(m.get("license_verified"), bool):
        out.append(f"{where}: license_verified must be true or false")
    if m.get("license_verified"):
        refs = re.findall(r"hf:([\w.-]+/[\w.-]+)@(\w+)", m.get("license_source") or "")
        if not refs or any(len(r[1]) != 40 for r in refs):
            out.append(f"{where}: a verified licence cites hf:<repo>@<40-char revision>")
    if m.get("weights_gb") is not None and not isinstance(m.get("weights_gb"), (int, float)):
        out.append(f"{where}: weights_gb is a number or null")
    mem = m.get("memory") or {}
    if "measured_gb" in mem:
        out.append(f"{where}: a model not measured on the Spark can't carry measured_gb")
    if mem.get("source") not in MEMORY_SOURCES or not mem.get("basis"):
        out.append(f"{where}: memory needs source estimate|reported and a basis")
    return out


@lru_cache(maxsize=1)
def download_groups() -> frozenset[str]:
    """Group names scripts/download_models.sh accepts (read from its dispatch line)."""
    import re

    src = (ROOT / "scripts" / "download_models.sh").read_text(encoding="utf-8")
    m = re.search(r'case "\$g" in ([\w|]+)\) log "group: \$g"', src)
    return frozenset(m.group(1).split("|")) if m else frozenset()


# ---------------------------------------------------------------- recommendation-only tiers (advisory)

def platform_of(hw: dict[str, Any]) -> str:
    """nvidia | apple | cpu, from a detect() / simulated() result (older results have no ``platform`` key)."""
    if hw.get("platform") in PLATFORMS:
        return hw["platform"]
    return "nvidia" if hw.get("gpu_class") in ("spark", "discrete", "unknown") else "cpu"


def _adv_matches(match: dict[str, Any], hw: dict[str, Any]) -> bool:
    plat = platform_of(hw)
    if match.get("platform") != plat:
        return False
    if plat == "nvidia":
        if hw.get("gpu_class") != "discrete":
            return False
        v = hw.get("vram_gb") or 0
        return match.get("min_vram_gb", 0) <= v < match.get("max_vram_gb", 1e9)
    if plat == "apple":
        mem = hw.get("memory_gb") or 0
        return match.get("min_memory_gb", 0) <= mem < match.get("max_memory_gb", 1e9)
    return True


def advisory_tier(hw: dict[str, Any], data: dict[str, Any] | None = None) -> str | None:
    """The recommendation-only tier for a computer the picker has no stack for, or None (e.g. a 6 GB card)."""
    data = data or load()
    return next((t["id"] for t in data.get("advisory_tiers") or [] if _adv_matches(t.get("match") or {}, hw)), None)


def advisory(tier_id: str, commercial: str = "any", data: dict[str, Any] | None = None,
             hw_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """One card per slot for a recommendation-only tier. Never changes what the app runs."""
    data = data or load()
    hw_data = hw_data or HW.load()
    t = next((x for x in data.get("advisory_tiers") or [] if x["id"] == tier_id), None)
    if t is None:
        raise KeyError(tier_id)
    labels = {s["id"]: s["label"] for s in data["slots"]}
    cards = []
    for sid in SLOT_IDS:
        pick = (t.get("picks") or {}).get(sid) or {}
        r = resolve(pick["model"], data, hw_data) if pick.get("model") else None
        hidden = r is not None and not commercial_ok(r, commercial)
        cards.append({"slot": sid, "slot_label": labels.get(sid, sid), "model": None if hidden else r,
                      "note": pick.get("note") or "", "hidden_by_license_filter": hidden})
    plat = (t.get("match") or {}).get("platform")
    return {"tier": t["id"], "label": t["label"], "status_label": t["status_label"], "verdict": t.get("verdict", ""),
            "platform": plat, "recommendation_only": True, "commercial": commercial, "cards": cards,
            "mac_caveats": list(data.get("mac_caveats") or []) if plat == "apple" else []}


def simulated(name: str, data: dict[str, Any] | None = None, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """A preview-mode computer from the manifest's simulations (KeyError if unknown)."""
    data = data or load()
    s = (data.get("simulations") or {})[name]
    gpus = list(s.get("gpus") or [])
    plat = s.get("platform") or "cpu"
    base = HW.classify_gpu(gpus) if plat == "nvidia" else {"gpu_class": "none", "unified_memory": plat == "apple",
                                                          "vram_gb": None, "gpu_name": s.get("chip")}
    return {"simulated": True, "simulation": name, "simulation_label": s.get("label"), "gpus": gpus,
            "memory_gb": s.get("memory_gb"), **base, "platform": plat, "chip": s.get("chip"), "machines": 1,
            "machines_source": "simulation", "machine_list": list((settings or {}).get("machine_list") or [])[:16],
            "notes": ["simulated hardware (preview mode)"]}


def advisory_problems(data: dict[str, Any] | None = None) -> list[str]:
    data = data if data is not None else load()
    out: list[str] = []
    models = data.get("models") or {}
    seen = set()
    for t in data.get("advisory_tiers") or []:
        tid = t.get("id")
        if tid in seen:
            out.append(f"advisory {tid}: duplicate id")
        seen.add(tid)
        plat = (t.get("match") or {}).get("platform")
        if plat not in PLATFORMS:
            out.append(f"advisory {tid}: match.platform must be one of {sorted(PLATFORMS)}")
        if "recommendation only" not in (t.get("status_label") or ""):
            out.append(f"advisory {tid}: status_label must say 'recommendation only'")
        picks = t.get("picks") or {}
        if set(picks) != set(SLOT_IDS):
            out.append(f"advisory {tid}: needs one pick per slot {list(SLOT_IDS)}")
        for sid, p in picks.items():
            mid = (p or {}).get("model")
            if mid is None:
                if not (p or {}).get("note"):
                    out.append(f"advisory {tid} {sid}: an empty pick needs a note saying why")
                continue
            m = models.get(mid)
            if m is None:
                out.append(f"advisory {tid} {sid}: model {mid!r} is not in models")
                continue
            if sid != m.get("slot") and sid not in (m.get("also_slots") or []):
                out.append(f"advisory {tid} {sid}: {mid} is a {m.get('slot')} model")
            if plat not in (m.get("platforms") or []):
                out.append(f"advisory {tid} {sid}: {mid} does not run on {plat}")
    for name, s in (data.get("simulations") or {}).items():
        if s.get("platform") not in PLATFORMS:
            out.append(f"simulation {name}: needs a platform")
    if data.get("advisory_tiers") and not any("15804" in c for c in data.get("mac_caveats") or []):
        out.append("mac_caveats must name the ComfyUI MPS bug (issue 15804)")
    return out


# ---------------------------------------------------------------- fit on one computer (Models screen)

PLATFORM_LABELS = {"nvidia": "NVIDIA", "apple": "Apple Silicon", "cpu": "CPU only"}
APPLE_GPU_SHARE = 0.75  # macOS lets the GPU use about three quarters of unified memory by default


def memory_budget_gb(hw: dict[str, Any]) -> tuple[float | None, str]:
    """The memory one model can use on this computer, and what it is (one GPU's VRAM, unified memory, or RAM)."""
    plat = platform_of(hw)
    if plat == "nvidia" and hw.get("gpu_class") == "discrete" and hw.get("vram_gb"):
        return float(hw["vram_gb"]), "GPU memory"
    mem = hw.get("memory_gb")
    if mem is None:
        return None, "memory"
    if plat == "apple":
        return round(float(mem) * APPLE_GPU_SHARE, 1), "of unified memory the GPU can use"
    if plat == "nvidia":
        return float(mem), "unified memory"
    return float(mem), "system memory"


def memory_need(model: dict[str, Any], tier: str | None = None) -> tuple[float | None, str | None]:
    """(GB, kind) for a resolved model: the picker tier's figure when it names this model on ``tier``, else the
    smallest tier figure, else the manifest's estimate. kind is measured | estimate | reported, or None if unknown."""
    rows = [r for r in model.get("memory_by_tier") or [] if r.get("gb") is not None]
    if rows:
        r = next((x for x in rows if x.get("tier") == tier), None) or min(rows, key=lambda x: x["gb"])
        return float(r["gb"]), r.get("kind") or "estimate"
    mem = model.get("memory") or {}
    if mem.get("est_gb") is not None:
        return float(mem["est_gb"]), mem.get("source") or "estimate"
    return None, None


def fit(model: dict[str, Any], hw: dict[str, Any], tier: str | None = None, where: str = "computer") -> dict[str, Any]:
    """Whether a resolved model suits a (detected or simulated) computer. Advisory only: it never changes a slot.
    status: fits | tight | too_big | wrong_platform | unknown. ``where`` names the target in the label: "computer"
    (this computer) or "studio" (the connected studio, OS-005)."""
    this = "your studio" if where == "studio" else "this computer"
    plat = platform_of(hw)
    plats = list(model.get("platforms") or [])
    need, kind = memory_need(model, tier)
    budget, what = memory_budget_gb(hw)
    base = {"platform": plat, "need_gb": need, "need_kind": kind, "budget_gb": budget, "budget_kind": what}
    if plats and plat not in plats:
        only = " or ".join(PLATFORM_LABELS.get(p, p) for p in plats)
        return {**base, "status": "wrong_platform", "label": f"Not for {this} · {only}"}
    if need is None or budget is None:
        return {**base, "status": "unknown", "label": "Memory need not known"}
    if need <= budget * 0.9:
        return {**base, "status": "fits", "label": f"Fits {this}"}
    if need <= budget:
        return {**base, "status": "tight", "label": "Tight fit"}
    return {**base, "status": "too_big", "label": "Needs more memory"}
