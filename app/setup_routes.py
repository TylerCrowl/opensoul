"""Setup API: /api/setup/*, used by the MCP setup tools (docs/SETUP.md). Mounted by app/server.py.

GET  /api/setup/hardware                      this computer (local, read-only), its picker tier and advisory tier
GET  /api/setup/recommend?tier=&simulate=&commercial=   the picker's recommendation plus the model slots
POST /api/setup/plan     {models, slot_changes, commercial}   dry-run install / swap plan (saves only the plan JSON)
POST /api/setup/apply    {plan_id, approval_token, approve}   runs an approved plan (preview mode: reports only)
POST /api/setup/slot     {slot, model, approval_token?, plan_id?}   plans or records a slot swap
GET  /api/setup/health                        missing files, manifest problems, free disk and memory

There is deliberately no approve route: the approval token is minted by the user with
``python -m opensoul.setup_engine approve <plan_id>``, never by an agent.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import hardware_routes as HR
from opensoul import model_manifest as MM
from opensoul import setup_engine as SE

router = APIRouter(prefix="/api/setup", tags=["setup"])


def _err(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except SE.SetupError as e:
        raise HTTPException(400, str(e)) from None


@router.get("/hardware")
def hardware(simulate: str | None = None, refresh: bool = False):
    return HR.detect(simulate=simulate, refresh=refresh)


@router.get("/recommend")
def recommend(tier: str | None = None, simulate: str | None = None, commercial: str = "any"):
    d = HR.recommend(tier=tier, simulate=simulate, commercial=commercial)
    return {**d, "slots": MM.slots(commercial, active=SE.active_slots(HR._data_dir()))}


class PlanBody(BaseModel):
    models: list[str] = []
    slot_changes: dict[str, str] = {}
    commercial: str = "any"


@router.post("/plan")
def plan(body: PlanBody):
    if body.commercial not in MM.COMMERCIAL_FILTERS:
        raise HTTPException(400, f"commercial must be one of {', '.join(MM.COMMERCIAL_FILTERS)}")
    plan = _err(SE.plan_install, body.models, body.slot_changes, commercial=body.commercial,
                data_dir=HR._data_dir())
    if plan.get("ok"):  # the command the USER runs to approve it; there is no approve route or tool
        plan["approve_command"] = SE.approve_command(plan, HR._data_dir())
    return plan


class ApplyBody(BaseModel):
    plan_id: str
    approval_token: str | None = None
    approve: bool = False


@router.post("/apply")
def apply(body: ApplyBody):
    return _err(SE.apply_install, body.plan_id, body.approval_token, approve_flag=body.approve,
                data_dir=HR._data_dir())


class SlotBody(BaseModel):
    slot: str
    model: str
    approval_token: str | None = None
    plan_id: str | None = None


@router.post("/slot")
def slot(body: SlotBody):
    return _err(SE.set_slot, body.slot, body.model, body.approval_token, body.plan_id, data_dir=HR._data_dir())


@router.get("/health")
def health() -> dict[str, Any]:
    return SE.health(HR._data_dir())
