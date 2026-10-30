"""Hardware picker API: /api/hardware/*. Mounted by app/server.py.

GET  /api/hardware/detect?simulate=<id>&refresh=1   what this computer has (local, read-only)
GET  /api/hardware/recommend?tier=<id>&simulate=<id>&commercial=any|allowed|open_only
                                                    the model per stage for a tier (manual, saved, or detected); when
                                                    that is the fallback, plus a recommendation-only tier ("advisory")
                                                    for 8-16 GB NVIDIA cards, Apple Silicon and CPU-only computers
GET  /api/hardware/tiers                            every tier with its tested / untested label
GET  /api/hardware/slots?commercial=any|allowed|open_only   one model slot per pipeline step (presets/model_manifest.yaml)
GET  /api/hardware/models?simulate=<id>&commercial=...       the Models screen: the slots (active model first, saved swaps
                                                    included) with a fit badge per option for this or a simulated computer
GET  /api/hardware/settings, POST /api/hardware/settings   machine count, manual tier, machine labels

``simulate`` works in preview mode (OPENSOUL_DRY_RUN) only, so the page and the tests run on a computer without a GPU.
Nothing here opens a network connection or looks for other machines.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from opensoul import hardware as HW
from opensoul import model_manifest as MM

router = APIRouter(prefix="/api/hardware", tags=["hardware"])
ROOT = Path(__file__).resolve().parents[1]
_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _dry() -> bool:
    return os.environ.get("OPENSOUL_DRY_RUN", "1").strip().lower() in {"1", "true", "yes", ""}


def _data_dir() -> Path:
    srv = sys.modules.get("app.server")
    d = getattr(srv, "DATA", None) if srv else None
    return Path(d) if d else Path(os.environ.get("OPENSOUL_DATA", ROOT / "data"))


def _hardware(simulate: str | None, refresh: bool, settings: dict[str, Any]) -> dict[str, Any]:
    if simulate:
        if not _dry():
            raise HTTPException(400, "Simulated hardware is for preview mode only.")
        try:
            return HW.simulated(simulate, settings=settings)
        except KeyError:
            pass
        try:  # the advisory tiers' simulated computers (presets/model_manifest.yaml)
            return MM.simulated(simulate, settings=settings)
        except KeyError:
            raise HTTPException(404, f"Unknown simulated computer: {simulate}") from None
    from opensoul import studio_info as SI

    if SI.studio_mode():  # OS-005: in studio mode the studio's GPU decides fit and tier, not this computer
        studio = SI.hardware(refresh=refresh)
        if studio:
            n, src = HW.machines_setting(settings)
            return {**studio, "machines": n, "machines_source": src,
                    "machine_list": list(settings.get("machine_list") or [])}
    with _lock:  # nvidia-smi once per server process unless asked again
        if refresh or "real" not in _cache:
            _cache["real"] = HW.detect(settings={})
        hw = dict(_cache["real"])
    n, src = HW.machines_setting(settings)
    hw.update(machines=n, machines_source=src, machine_list=list(settings.get("machine_list") or []))
    if SI.studio_mode():
        hw["studio_unreachable"] = True  # studio mode, but the studio did not answer: say so, judge this computer
    return hw


def _summary(hw: dict[str, Any]) -> str:
    s = HW.describe_hardware(hw)
    if hw.get("studio"):
        return "Your studio: " + s
    if hw.get("studio_unreachable"):
        return "The studio did not answer. This computer: " + s
    return s


@router.get("/detect")
def detect(simulate: str | None = None, refresh: bool = False):
    settings = HW.load_settings(_data_dir())
    hw = _hardware(simulate, refresh, settings)
    tier = HW.pick_tier(hw)
    return {"hardware": hw, "summary": _summary(hw), "auto_tier": tier, "dry_run": _dry(),
            "advisory_tier": MM.advisory_tier(hw) if tier == "fallback" else None}


def _commercial(card: dict[str, Any]) -> str:
    return MM.COMMERCIAL.get(card.get("license_class"), "no")


@router.get("/recommend")
def recommend(tier: str | None = None, simulate: str | None = None, commercial: str = "any"):
    if commercial not in MM.COMMERCIAL_FILTERS:
        raise HTTPException(400, f"commercial must be one of {', '.join(MM.COMMERCIAL_FILTERS)}")
    data = HW.load()
    settings = HW.load_settings(_data_dir())
    hw = _hardware(simulate, False, settings)
    auto = HW.pick_tier(hw, data)
    if tier and tier != "auto":
        if tier not in HW.tier_ids(data):
            raise HTTPException(404, f"Unknown tier: {tier}")
        chosen, source = tier, "manual"
    elif settings.get("tier_override") in HW.tier_ids(data) and not simulate:
        chosen, source = settings["tier_override"], "setting"
    else:
        chosen, source = auto, ("simulated" if simulate else "detected")
    rec = HW.recommend(chosen, data)
    for c in rec["cards"]:  # licence filter: mark, never drop, so the page can say what was hidden and why
        c["commercial_use"] = _commercial(c)
        c["hidden_by_license_filter"] = not MM.commercial_ok(c, commercial)
    mdata = MM.load()
    adv_id = MM.advisory_tier(hw, mdata) if rec["fallback"] else None
    return {
        "hardware": hw, "summary": _summary(hw), "auto_tier": auto, "tier_source": source,
        "recommendation": rec, "tiers": HW.tiers_summary(data), "dry_run": _dry(),
        "simulations": ([{"id": k, "label": v.get("label")} for k, v in (data.get("simulations") or {}).items()]
                        if _dry() else []),
        "advisory": MM.advisory(adv_id, commercial, mdata, data) if adv_id else None,
        "advisory_simulations": ([{"id": k, "label": v.get("label")} for k, v in (mdata.get("simulations") or {}).items()]
                                 if _dry() else []),
        "commercial": commercial,
        "settings": settings,
    }


@router.get("/tiers")
def tiers():
    return {"tiers": HW.tiers_summary(), "problems": HW.problems()}


@router.get("/settings")
def get_settings():
    s = HW.load_settings(_data_dir())
    n, src = HW.machines_setting(s)
    return {"settings": s, "machines": n, "machines_source": src}


class HardwareSettings(BaseModel):
    machines: int | None = None
    tier_override: str | None = None
    machine_list: list[dict[str, Any]] | None = None


@router.post("/settings")
def post_settings(body: HardwareSettings):
    new = body.model_dump(exclude_unset=True)
    try:
        s = HW.save_settings(_data_dir(), new)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    n, src = HW.machines_setting(s)
    return {"settings": s, "machines": n, "machines_source": src}


@router.get("/slots")
def slots(commercial: str = "any"):
    """The model manifest: per slot the app default, the active model and the options, with licence, memory, disk
    and source. ``commercial`` filters by licence (see opensoul/model_manifest.py commercial_ok). Read-only."""
    from opensoul import model_manifest as MM

    if commercial not in MM.COMMERCIAL_FILTERS:
        raise HTTPException(400, f"commercial must be one of {', '.join(MM.COMMERCIAL_FILTERS)}")
    return {"slots": MM.slots(commercial), "commercial": commercial, "problems": MM.problems()}


@router.get("/models")
def models(simulate: str | None = None, commercial: str = "any"):
    """The Models screen (app/web/static/models.js): every slot with its active model and the alternatives, each with
    a fit badge for this computer or, in preview mode, a simulated one. Read-only: plans go through POST
    /api/setup/plan and only the user can approve one (python -m opensoul.setup_engine approve)."""
    from opensoul import setup_engine as SE

    if commercial not in MM.COMMERCIAL_FILTERS:
        raise HTTPException(400, f"commercial must be one of {', '.join(MM.COMMERCIAL_FILTERS)}")
    settings = HW.load_settings(_data_dir())
    hw = _hardware(simulate, False, settings)
    data = HW.load()
    tier = HW.pick_tier(hw, data)
    out = MM.slots(commercial, active=SE.active_slots(_data_dir()))
    from opensoul import studio_info as SI

    have = SI.model_files() if hw.get("studio") else None  # OS-005: model presence from the studio's ComfyUI
    every = {s["id"]: s for s in MM.slots("any", check_files=False, active=SE.active_slots(_data_dir()))}
    for s in out:
        for o in s["options"]:
            o["fit"] = MM.fit(o, hw, tier, where="studio" if hw.get("studio") else "computer")
            if have is not None and o.get("in_app"):
                o["installed"] = SI.installed_on_studio(o.get("files") or [], have)
                o["installed_where"] = "studio"
            o["is_active"] = o["id"] == s["active"]
            o["is_default"] = o["id"] == s["default"]
        s["hidden_count"] = len(every[s["id"]]["options"]) - len(s["options"])
        s["options"].sort(key=lambda o: not o["is_active"])  # active first, then the manifest's order
    mdata = MM.load()
    return {
        "hardware": hw, "summary": _summary(hw), "tier": tier, "dry_run": _dry(), "commercial": commercial,
        "studio": bool(hw.get("studio")),
        "slots": out,
        "simulations": ([{"id": k, "label": v.get("label")} for k, v in (data.get("simulations") or {}).items()]
                        + [{"id": k, "label": v.get("label")} for k, v in (mdata.get("simulations") or {}).items()]
                        if _dry() else []),
    }
