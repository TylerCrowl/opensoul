"""Installer and slot-swap engine: plan -> approve -> apply. Dry run first, always.

    python -m opensoul.setup_engine plan --model ltx25_bf16 [--model kokoro] [--commercial allowed]
    python -m opensoul.setup_engine approve <plan_id> [--accept-licenses]      # the USER runs this: prints a token
    python -m opensoul.setup_engine apply <plan_id> --token <token> --approve  # runs the plan's commands
    python -m opensoul.setup_engine slot <slot> <model>                        # plans a slot swap (no downloads)
    python -m opensoul.setup_engine rollback                                   # undoes the last slot swap
    python -m opensoul.setup_engine health

Rules (docs/SETUP.md):
- A plan is computed locally: which models, which ``scripts/download_models.sh`` groups or setup scripts, how much
  disk (an upper bound from the Hub file sizes), whether it fits the free disk, which licences need a yes first, and
  which slot changes. Making a plan changes nothing but a JSON file in the app's data folder.
- Applying needs the plan id, a one-time approval token that only ``approve`` mints (the MCP server has no approve
  tool), and an explicit ``--approve``. Tokens are stored hashed, expire after 30 minutes and work once. A plan that was
  edited after approval is refused.
- In preview mode (``OPENSOUL_DRY_RUN=1``, the default) apply only reports what it would run.
- Only models the app runs and that are not blocked can be installed; candidates not in the app yet can't.
- No network, firewall, driver or OS changes and no sudo here: the commands are the repo's own download and setup
  scripts, run without a shell. Every apply and slot change is logged; a slot swap can be rolled back in one step.
- The active slot file (``settings/slots.json``) is a record for the setup tools; the render path does not read it
  yet, so nothing an existing story or default uses changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from opensoul import hardware as HW
from opensoul import model_manifest as MM

ROOT = Path(__file__).resolve().parents[1]
TOKEN_TTL_S = 30 * 60
Executor = Callable[..., Any]


class SetupError(ValueError):
    pass


def _dry() -> bool:
    return os.environ.get("OPENSOUL_DRY_RUN", "1").strip().lower() in {"1", "true", "yes", ""}


def data_dir_default() -> Path:
    return Path(os.environ.get("OPENSOUL_DATA", ROOT / "data"))


def _setup_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "setup"


def _plan_path(data_dir: Path, plan_id: str) -> Path:
    if not plan_id or not all(c in "0123456789abcdef" for c in plan_id) or len(plan_id) != 16:
        raise SetupError("plan_id must be the 16-character id plan_install returned")
    return _setup_dir(data_dir) / "plans" / f"{plan_id}.json"


def _log(data_dir: Path, event: dict[str, Any]) -> None:
    p = _setup_dir(data_dir) / "log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": round(time.time(), 3), **event}) + "\n")


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---------------------------------------------------------------- disk

def free_disk_gb(path: Path | None = None) -> float | None:
    """Free space where models go (the nearest existing folder of the ComfyUI models dir). Local, read-only."""
    from opensoul import models_registry as MR

    p = Path(path) if path else MR.comfy_models_dir()
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return round(shutil.disk_usage(p).free / 1e9, 1)
    except OSError:
        return None


# ---------------------------------------------------------------- slots state

def slots_path(data_dir: Path) -> Path:
    return Path(data_dir) / "settings" / "slots.json"


def load_slots(data_dir: Path) -> dict[str, Any]:
    try:
        d = json.loads(slots_path(data_dir).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def active_slots(data_dir: Path) -> dict[str, str]:
    return dict(load_slots(data_dir).get("active") or {})


def _write_slots(data_dir: Path, state: dict[str, Any]) -> None:
    p = slots_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


# ---------------------------------------------------------------- plan

def _commands(model: dict[str, Any]) -> list[dict[str, Any]]:
    inst = model.get("install") or {}
    out = []
    groups = list(inst.get("download_groups") or [])
    if groups:
        out.append({"argv": ["bash", "scripts/download_models.sh", *groups], "env": dict(inst.get("env") or {}),
                    "why": f"download {model['label']}"})
    if inst.get("setup"):
        out.append({"argv": ["bash", inst["setup"]], "env": {}, "why": f"install {model['label']} (own venv)"})
    return out


def plan_install(models: list[str] | None = None, slot_changes: dict[str, str] | None = None, *,
                 commercial: str = "any", data_dir: Path | None = None, hw: dict[str, Any] | None = None,
                 save: bool = True) -> dict[str, Any]:
    """Dry run: what installing ``models`` (and/or switching ``slot_changes`` {slot: model}) would do. Changes nothing
    except saving the plan JSON (so it can be approved and applied by id)."""
    data_dir = Path(data_dir or data_dir_default())
    mdata = MM.load()
    hw_data = HW.load()
    slot_changes = dict(slot_changes or {})
    wanted = list(dict.fromkeys([*(models or []), *slot_changes.values()]))
    if not wanted:
        raise SetupError("name at least one model or slot change")
    errors: list[str] = []
    items: list[dict[str, Any]] = []
    blocked_ids = {b["id"] for b in MM.blocked(mdata, hw_data)}
    for mid in wanted:
        if mid in blocked_ids:
            errors.append(f"{mid}: blocked licence, never installed")
            continue
        if mid not in mdata["models"]:
            errors.append(f"{mid}: not in presets/model_manifest.yaml")
            continue
        r = MM.resolve(mid, mdata, hw_data)
        if not r["in_app"]:
            errors.append(f"{mid}: not in the app yet ({r.get('in_app_note')}); OpenSoul can't install it")
            continue
        if not MM.commercial_ok(r, commercial):
            errors.append(f"{mid}: licence {r['license']} is outside the '{commercial}' filter")
            continue
        inst = MM.installed(r)
        items.append({"model": mid, "label": r["label"], "slot": r["slot"], "license": r["license"],
                      "license_class": r["license_class"], "commercial_use": r["commercial_use"],
                      "installed": inst, "weights_gb": r["weights_gb"],
                      "download_gb": 0 if inst else (r["weights_gb"] or 0),
                      "gated": bool((r.get("install") or {}).get("gated")),
                      "manual_steps": list((r.get("install") or {}).get("manual_steps") or []),
                      "commands": [] if inst else _commands(r), "memory": r["memory"],
                      "memory_by_tier": r["memory_by_tier"]})
    changes = []
    current = {s["id"]: s["active"] for s in MM.slots(data=mdata, hw_data=hw_data, check_files=False,
                                                      active=active_slots(data_dir))}
    for sid, mid in slot_changes.items():
        if sid not in MM.SLOT_IDS:
            errors.append(f"unknown slot {sid!r}")
            continue
        m = mdata["models"].get(mid) or {}
        if m and sid != m.get("slot") and sid not in (m.get("also_slots") or []):
            errors.append(f"{mid} is a {m.get('slot')} model, not a {sid} model")
            continue
        changes.append({"slot": sid, "from": current.get(sid), "to": mid})
    need = round(sum(i["download_gb"] for i in items), 2)
    free = free_disk_gb()
    acks = [i["model"] for i in items if i["license_class"] in ("ai_label", "use_restricted") and not i["installed"]]
    tier = HW.pick_tier(hw, hw_data) if hw else None
    body = {"models": [{k: i[k] for k in ("model", "installed", "commands")} for i in items],
            "slot_changes": changes, "commercial": commercial}
    plan = {
        "kind": "install" if any(i["commands"] for i in items) else "slot",
        "items": items, "slot_changes": changes, "errors": errors, "ok": not errors,
        "download_gb_upper_bound": need, "free_disk_gb": free,
        "disk_fits": None if free is None else need <= free,
        "license_acks_needed": acks,
        "gated_downloads": [i["model"] for i in items if i["gated"] and not i["installed"]],
        "tier": tier, "commercial": commercial, "dry_run": True,
        "note": ("Plan only: OpenSoul did not download or change anything. The download size is an upper bound: "
                 "it counts files that models share once per model. To run the plan, the user approves it "
                 "(approve). Then the agent calls apply with the token and the approve flag."),
        "content_sha256": _sha(body), "created": round(time.time(), 3),
    }
    plan["plan_id"] = plan["content_sha256"][:16]
    if save and plan["ok"]:
        p = _plan_path(data_dir, plan["plan_id"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"plan": plan, "body": body, "approval": None}, indent=2) + "\n", encoding="utf-8")
        _log(data_dir, {"event": "plan", "plan_id": plan["plan_id"], "models": wanted, "slot_changes": changes})
    return plan


def _load_plan(data_dir: Path, plan_id: str) -> dict[str, Any]:
    p = _plan_path(data_dir, plan_id)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SetupError(f"no saved plan {plan_id}; make one with plan_install first") from None


# ---------------------------------------------------------------- approve (the user's step)

def approve(plan_id: str, *, data_dir: Path | None = None, accept_licenses: bool = False) -> dict[str, Any]:
    """Mint a one-time approval token for a saved plan. This is the user's consent: the MCP server never calls it."""
    data_dir = Path(data_dir or data_dir_default())
    rec = _load_plan(data_dir, plan_id)
    plan = rec["plan"]
    if plan["license_acks_needed"] and not accept_licenses:
        raise SetupError("this plan needs a yes to these licences first (--accept-licenses): "
                         + ", ".join(plan["license_acks_needed"]))
    token = secrets.token_urlsafe(24)
    rec["approval"] = {"token_sha256": hashlib.sha256(token.encode()).hexdigest(), "expires": time.time() + TOKEN_TTL_S,
                       "used": False, "licenses_accepted": list(plan["license_acks_needed"]),
                       "content_sha256": _sha(rec["body"])}
    _plan_path(data_dir, plan_id).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    _log(data_dir, {"event": "approve", "plan_id": plan_id, "licenses_accepted": rec["approval"]["licenses_accepted"]})
    return {"plan_id": plan_id, "approval_token": token, "expires_in_s": TOKEN_TTL_S}


def _home_arg(p: Path) -> str:
    """A shell argument for ``p`` with the home folder written as ~ (no account name on screen), else quoted."""
    import os
    import shlex

    p, home = Path(p).resolve(), Path.home().resolve()
    if os.name != "nt" and home != Path("/") and p.is_relative_to(home):
        rest = p.relative_to(home).as_posix()
        return "~/" + shlex.quote(rest) if rest else "~"
    return shlex.quote(str(p))


def approve_command(plan: dict[str, Any], data_dir: Path | None = None) -> str:
    """The exact command the user pastes into a terminal to approve ``plan``. Shown by the Models screen; nothing in
    the app or the MCP server runs it. From a desktop package (OPENSOUL_LAUNCHED=1) it uses the package's own Python
    and folder, so it works without Python on the PATH; paths under the home folder are written with ~."""
    import os
    import shlex
    import sys

    tail = ["-m", "opensoul.setup_engine"]
    if data_dir is not None and Path(data_dir).resolve() != (ROOT / "data").resolve():
        tail += ["--data", "\0"]
    tail += ["approve", plan["plan_id"]]
    if plan.get("license_acks_needed"):
        tail.append("--accept-licenses")
    rest = " ".join(_home_arg(Path(data_dir)) if a == "\0" else shlex.quote(a) for a in tail)
    if os.environ.get("OPENSOUL_LAUNCHED") == "1":
        return f"cd {_home_arg(ROOT)} && {_home_arg(Path(sys.executable))} -I {rest}"
    return f"python {rest}"


def _check_token(rec: dict[str, Any], token: str | None) -> None:
    a = rec.get("approval") or {}
    if not token:
        raise SetupError("approval token required: the user approves the plan first")
    if not a or a.get("used"):
        raise SetupError("this plan has no unused approval; ask the user to approve it again")
    if time.time() > float(a.get("expires") or 0):
        raise SetupError("the approval token expired; ask the user to approve the plan again")
    if not secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), a.get("token_sha256") or ""):
        raise SetupError("approval token does not match this plan")
    if _sha(rec["body"]) != a.get("content_sha256") or rec["plan"]["content_sha256"] != a.get("content_sha256"):
        raise SetupError("the plan changed after the user approved it. Make a new plan. Then approve it.")


# ---------------------------------------------------------------- apply

def apply_install(plan_id: str, approval_token: str | None, *, approve_flag: bool = False,
                  data_dir: Path | None = None, executor: Executor | None = None,
                  dry_run: bool | None = None) -> dict[str, Any]:
    """Run an approved plan. Needs the token AND ``approve_flag``. In preview mode it only reports what it would run."""
    data_dir = Path(data_dir or data_dir_default())
    if not approve_flag:
        raise SetupError("apply needs the explicit approve flag (--approve / approve=true)")
    rec = _load_plan(data_dir, plan_id)
    _check_token(rec, approval_token)
    plan = rec["plan"]
    cmds = [c for i in plan["items"] for c in i["commands"]]
    dry = _dry() if dry_run is None else dry_run
    if dry:
        _log(data_dir, {"event": "apply_dry_run", "plan_id": plan_id})
        return {"plan_id": plan_id, "executed": False, "dry_run": True, "would_run": cmds,
                "would_change_slots": plan["slot_changes"],
                "note": "Preview mode (OPENSOUL_DRY_RUN): OpenSoul ran nothing. The token is still valid."}
    if cmds:
        free = free_disk_gb()
        if free is not None and plan["download_gb_upper_bound"] > free:
            raise SetupError(f"not enough free disk: need up to {plan['download_gb_upper_bound']} GB, {free} GB free")
    rec["approval"]["used"] = True  # one use, even if a command fails
    _plan_path(data_dir, plan_id).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    run = executor or subprocess.run
    results = []
    for c in cmds:
        env = {**os.environ, **{k: str(v) for k, v in (c.get("env") or {}).items()}}
        r = run(list(c["argv"]), cwd=str(ROOT), env=env, check=False)
        code = int(getattr(r, "returncode", 1))
        results.append({"argv": c["argv"], "returncode": code})
        _log(data_dir, {"event": "apply_cmd", "plan_id": plan_id, "argv": c["argv"], "returncode": code})
        if code != 0:
            return {"plan_id": plan_id, "executed": True, "ok": False, "results": results,
                    "note": "A command failed, so OpenSoul skipped the later commands and slot changes. See the setup log."}
    if plan["slot_changes"]:
        _apply_slot_changes(data_dir, plan["slot_changes"], plan_id)
    return {"plan_id": plan_id, "executed": True, "ok": True, "results": results,
            "slots": active_slots(data_dir)}


def _apply_slot_changes(data_dir: Path, changes: list[dict[str, Any]], plan_id: str) -> None:
    state = load_slots(data_dir)
    active = dict(state.get("active") or {})
    history = list(state.get("history") or [])
    history.append({"plan_id": plan_id, "before": dict(active), "ts": round(time.time(), 3)})
    for ch in changes:
        active[ch["slot"]] = ch["to"]
    _write_slots(data_dir, {"active": active, "history": history[-50:]})
    _log(data_dir, {"event": "slots", "plan_id": plan_id, "changes": changes})


def set_slot(slot: str, model: str, approval_token: str | None = None, plan_id: str | None = None, *,
             data_dir: Path | None = None, require_installed: bool | None = None) -> dict[str, Any]:
    """Swap a slot's active model. Without a token: returns a slot plan to approve (changes nothing). With the plan id
    and the user's token: records the swap (installed models only, outside preview mode)."""
    data_dir = Path(data_dir or data_dir_default())
    if approval_token is None:
        plan = plan_install(slot_changes={slot: model}, data_dir=data_dir)
        if plan["ok"]:
            item = next(i for i in plan["items"] if i["model"] == model)
            needs_install = item["installed"] is False and not _dry()
            if needs_install:
                plan["note"] = f"{model} is not installed: install it first (plan_install) or approve this plan to do both."
        return plan
    if not plan_id:
        raise SetupError("set_slot with a token needs the plan_id it approves")
    rec = _load_plan(data_dir, plan_id)
    if [(c["slot"], c["to"]) for c in rec["plan"]["slot_changes"]] != [(slot, model)]:
        raise SetupError("that plan is not this slot change")
    must_be_installed = (not _dry()) if require_installed is None else require_installed
    item = next((i for i in rec["plan"]["items"] if i["model"] == model), None)
    if must_be_installed and item and item["commands"]:
        raise SetupError(f"{model} is not installed: apply its install plan first")
    _check_token(rec, approval_token)
    rec["approval"]["used"] = True
    _plan_path(data_dir, plan_id).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    _apply_slot_changes(data_dir, rec["plan"]["slot_changes"], plan_id)
    return {"slot": slot, "model": model, "slots": active_slots(data_dir),
            "note": "Recorded. The render path does not read the slot file yet; story engines and defaults are unchanged."}


def rollback(*, data_dir: Path | None = None) -> dict[str, Any]:
    """Undo the last slot change (one step)."""
    data_dir = Path(data_dir or data_dir_default())
    state = load_slots(data_dir)
    history = list(state.get("history") or [])
    if not history:
        raise SetupError("nothing to roll back")
    last = history.pop()
    _write_slots(data_dir, {"active": last["before"], "history": history})
    _log(data_dir, {"event": "rollback", "plan_id": last.get("plan_id")})
    return {"slots": dict(last["before"]), "rolled_back": last.get("plan_id")}


# ---------------------------------------------------------------- health

def _mem_available_gb() -> float | None:
    try:
        import re

        m = re.search(r"^MemAvailable:\s+(\d+)\s*kB", Path("/proc/meminfo").read_text(), re.M)
        return round(int(m.group(1)) / 1024 / 1024, 1) if m else None
    except OSError:
        return None


def health(data_dir: Path | None = None) -> dict[str, Any]:
    """Missing files per stage, manifest and picker problems, free disk and memory. Local and read-only."""
    from opensoul import models_registry as MR

    data_dir = Path(data_dir or data_dir_default())
    stages = MR.stage_status()
    problems = {"model_manifest": MM.problems(), "hardware_profiles": HW.problems()}
    missing = [{"stage": s["id"], "status": s["status"], "missing_files": s["missing_files"],
                "download_hint": s["download_hint"]} for s in stages if s["status"] in ("missing", "optional_missing")]
    return {"ok": not any(problems.values()) and not any(m["status"] == "missing" for m in missing),
            "missing": missing, "problems": problems, "free_disk_gb": free_disk_gb(),
            "memory_available_gb": _mem_available_gb(), "slots": active_slots(data_dir), "dry_run": _dry()}


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opensoul.setup_engine", description="OpenSoul setup: plan, approve, apply")
    ap.add_argument("--data", default=None, help="app data folder (default $OPENSOUL_DATA or ./data)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--model", action="append", default=[])
    p.add_argument("--slot", action="append", default=[], help="slot=model")
    p.add_argument("--commercial", default="any", choices=MM.COMMERCIAL_FILTERS)
    a = sub.add_parser("approve")
    a.add_argument("plan_id")
    a.add_argument("--accept-licenses", action="store_true")
    x = sub.add_parser("apply")
    x.add_argument("plan_id")
    x.add_argument("--token", required=True)
    x.add_argument("--approve", action="store_true", help="required: yes, run this plan")
    s = sub.add_parser("slot")
    s.add_argument("slot")
    s.add_argument("model")
    s.add_argument("--token", default=None)
    s.add_argument("--plan-id", default=None)
    sub.add_parser("rollback")
    sub.add_parser("health")
    args = ap.parse_args(argv)
    dd = Path(args.data) if args.data else None
    try:
        if args.cmd == "plan":
            changes = dict(kv.split("=", 1) for kv in args.slot)
            out = plan_install(args.model, changes, commercial=args.commercial, data_dir=dd)
        elif args.cmd == "approve":
            out = approve(args.plan_id, data_dir=dd, accept_licenses=args.accept_licenses)
        elif args.cmd == "apply":
            out = apply_install(args.plan_id, args.token, approve_flag=args.approve, data_dir=dd)
        elif args.cmd == "slot":
            out = set_slot(args.slot, args.model, args.token, args.plan_id, data_dir=dd)
        elif args.cmd == "rollback":
            out = rollback(data_dir=dd)
        else:
            out = health(dd)
    except SetupError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
