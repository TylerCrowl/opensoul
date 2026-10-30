"""Music model registry: presets/music_models.json -> the Music tab's dropdowns.

Same idea as ``presets/models.yaml`` (``opensoul.models_registry``): each model is a swappable backend with an
``id``, a ``license`` and ``files`` (same path rules, local existence checks only, no network). It is JSON because
the Music tab reads it straight into a dropdown, like ``presets/text_master.json``.

A model is offered only when it is *usable*: ``enabled``, ``status == "confirmed"``, ``confirmed_by`` set, a
license allowed by ``license_allowlist`` / ``license_rules`` (CC-BY needs a credit line, the LTX-2 community
licences need the AI-generated label; non-commercial, research-only, gated and unlicensed are blocked; anything
else is undecided and stays off), every spec filled in, a runner whose ComfyUI workflow
file exists, and (for anything that isn't OpenSoul's own code) a pinned ``revision``: a git sha after ``@`` or a
sha256. An entry that is enabled but not usable is a registry error (:func:`problems`), so nobody can switch on a
model with a guessed license or an unpinned download. See docs/MUSIC.md.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "presets" / "music_models.json"
ROLES = ("song", "stems", "analysis")
RUNNER_KINDS = ("comfyui", "python", "runner")
FIELDS = ("id", "name", "role", "status", "enabled", "license", "license_url", "confirmed_by", "vram_gb",
          "max_seconds", "vocals", "lyrics_input", "prompt_input", "runner", "files", "download_group", "notes")
OPTIONAL = ("preview_only", "revision", "gpu_validated", "credit", "ai_label")  # preview_only: offered only in preview mode
SPECS = ("license", "confirmed_by", "vram_gb", "max_seconds", "vocals", "lyrics_input", "prompt_input")
EMPTY = {"song": "No song model is set up yet.", "stems": "No vocal splitter is set up yet.",
         "analysis": "No beat finder is set up."}


PINNED = re.compile(r"(@[0-9a-f]{40}$)|(^[0-9a-f]{64}$)")


class RegistryError(ValueError):
    pass


def load(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_REGISTRY
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data.get("models"), list):
        raise RegistryError(f"music registry has no models list: {p.name}")
    return data


def allowed_licenses(data: dict[str, Any]) -> set[str]:
    rules = data.get("license_rules") or {}
    return set(data.get("license_allowlist") or []) | set(rules.get("needs_ai_label") or [])


def blocked(lic: str | None, data: dict[str, Any]) -> bool:
    """Non-commercial, research-only, gated-without-redistribution or no licence at all."""
    if not lic:
        return True
    pats = (data.get("license_rules") or {}).get("blocked_patterns") or []
    return any(re.search(p, lic, re.I) for p in pats)


def license_problem(model: dict[str, Any], data: dict[str, Any]) -> str:
    """'' when the model's licence is allowed for the contest, else a plain reason."""
    lic = model.get("license")
    rules = data.get("license_rules") or {}
    if blocked(lic, data):
        return f"license {lic} is blocked (non-commercial, research-only, gated or unlicensed)" if lic else ""
    if lic not in allowed_licenses(data):
        return f"license {lic} is undecided: off until it is reviewed"
    if lic in (rules.get("needs_credit") or []) and not model.get("credit"):
        return f"license {lic} needs a credit line"
    if lic in (rules.get("needs_ai_label") or []) and model.get("ai_label") is not True:
        return f"license {lic} needs the AI-generated label (ai_label)"
    return ""


def is_blocked(model: dict[str, Any], data: dict[str, Any]) -> bool:
    """Blocked entries are kept for the record but never offered, never listed as 'not ready', never enabled."""
    return model.get("status") == "blocked" or (bool(model.get("license")) and blocked(model["license"], data))


def undecided(path: str | Path | None = None) -> list[dict[str, str]]:
    """Models whose licence is neither allowed nor blocked: off by default, listed here for a decision."""
    data = load(path)
    return [{"id": m["id"], "license": m["license"]} for m in data["models"]
            if m.get("license") and not blocked(m["license"], data) and m["license"] not in allowed_licenses(data)]


def why_not_usable(model: dict[str, Any], data: dict[str, Any]) -> list[str]:
    """Plain reasons a model can't be offered ([] = usable). Disabled models say so first."""
    why: list[str] = []
    if not model.get("enabled"):
        why.append("not enabled")
    if model.get("status") == "blocked":
        why.append("blocked: its licence is not allowed for the contest")
    elif model.get("status") != "confirmed":
        why.append("licence not confirmed yet")
    missing = [k for k in SPECS if model.get(k) is None or model.get(k) == ""]
    if missing:
        why.append("missing " + ", ".join(missing))
    lic_why = license_problem(model, data)
    if lic_why:
        why.append(lic_why)
    runner = model.get("runner") or {}
    if runner.get("kind") not in RUNNER_KINDS:
        why.append("no runner")
    elif runner["kind"] == "comfyui" and not workflow_file(model):
        why.append("no ComfyUI workflow")
    elif runner["kind"] == "comfyui" and not workflow_file(model).is_file():  # type: ignore[union-attr]
        wf = workflow_file(model)
        shown = wf.relative_to(ROOT).as_posix() if wf.is_relative_to(ROOT) else wf.name  # type: ignore[union-attr]
        why.append(f"workflow file {shown} is missing")
    elif runner["kind"] in ("python", "runner") and not runner.get("module"):
        why.append("no runner module")
    if not own_code(model) and not pinned(model.get("revision")):
        why.append("no pinned revision (a git sha after @, or a sha256)")
    return why


def own_code(model: dict[str, Any]) -> bool:
    """OpenSoul's own code (this repo's licence, nothing downloaded): needs no revision pin."""
    return model.get("license_url") == "LICENSE" and not model.get("files")


def pinned(rev: Any) -> bool:
    """Every revision value is an exact commit (``repo@<40-hex sha>``) or a sha256; branch names and null don't count."""
    vals = list(rev.values()) if isinstance(rev, dict) else [rev]
    return bool(vals) and all(isinstance(v, str) and PINNED.search(v.strip()) for v in vals)


def workflow_file(model: dict[str, Any]) -> Path | None:
    """The model's API-format workflow: env OPENSOUL_<ID>_WORKFLOW, else ``runner.workflow`` (repo-relative)."""
    env = os.environ.get(f"OPENSOUL_{str(model.get('id', '')).upper()}_WORKFLOW")
    rel = env or (model.get("runner") or {}).get("workflow")
    if not rel:
        return None
    p = Path(rel)
    return p if p.is_absolute() else ROOT / p


def usable(model: dict[str, Any], data: dict[str, Any]) -> bool:
    return not why_not_usable(model, data)


def problems(data: dict[str, Any]) -> list[str]:
    """Registry errors: bad ids or roles, duplicates, unknown fields, or an enabled model that isn't usable."""
    out: list[str] = []
    seen: set[str] = set()
    for i, m in enumerate(data.get("models") or []):
        mid = m.get("id")
        if not mid or not isinstance(mid, str) or not mid.replace("_", "").isalnum() or mid != mid.lower():
            out.append(f"model #{i + 1}: id must be lower_snake_case")
        if mid in seen:
            out.append(f"{mid}: duplicate id")
        seen.add(mid)
        if m.get("role") not in ROLES:
            out.append(f"{mid}: role must be one of {', '.join(ROLES)}")
        extra = sorted(set(m) - set(FIELDS) - set(OPTIONAL))
        if extra:
            out.append(f"{mid}: unknown fields {', '.join(extra)}")
        lacking = sorted(set(FIELDS) - set(m))
        if lacking:
            out.append(f"{mid}: missing fields {', '.join(lacking)}")
        if m.get("enabled"):
            why = [w for w in why_not_usable(m, data) if w != "not enabled"]
            if why:
                out.append(f"{mid}: enabled but {'; '.join(why)}")
    return out


def models(role: str | None = None, path: str | Path | None = None, *, usable_only: bool = False) -> list[dict[str, Any]]:
    data = load(path)
    return [m for m in data["models"] if (role is None or m.get("role") == role) and (not usable_only or usable(m, data))]


def get(model_id: str, path: str | Path | None = None) -> dict[str, Any]:
    for m in load(path)["models"]:
        if m.get("id") == model_id:
            return m
    raise RegistryError(f"Unknown music model {model_id!r}.")


def installed(model: dict[str, Any]) -> bool:
    """All of the model's files are on disk (same path rules and check as presets/models.yaml)."""
    from opensoul.models_registry import _missing_files

    return not _missing_files(list(model.get("files") or []))


def offered(m: dict[str, Any], data: dict[str, Any], preview: bool) -> bool:
    return usable(m, data) and (preview or not m.get("preview_only"))


def default_id(role: str, data: dict[str, Any], preview: bool) -> str:
    d = data.get("defaults") or {}
    return str((d.get(f"{role}_preview") if preview else None) or d.get(role) or "")


def choices(role: str, path: str | Path | None = None, *, preview: bool = False) -> dict[str, Any]:
    """Dropdown data for one role. Never offers an unusable model; says why the list is empty instead.
    ``preview`` (dry run) also offers the preview_only entries; the studio never does."""
    data = load(path)
    opts = []
    for m in data["models"]:
        if m.get("role") != role or not offered(m, data, preview):
            continue
        opts.append({"id": m["id"], "label": m["name"], "license": m["license"], "vram_gb": m["vram_gb"],
                     "max_seconds": m["max_seconds"], "vocals": bool(m["vocals"]), "lyrics_input": bool(m["lyrics_input"]),
                     "preview": bool(m.get("preview_only")), "gpu_validated": m.get("gpu_validated"),
                     "credit": m.get("credit") or "", "installed": installed(m), "download_hint": f"./scripts/download_models.sh {m['download_group']}"
                     if m.get("download_group") else ""})
    pending = []
    for m in data["models"]:
        if m.get("role") == role and not usable(m, data) and not is_blocked(m, data):
            why = [w for w in why_not_usable(m, data) if w != "not enabled"] or ["switched off"]
            pending.append({"id": m["id"], "label": m["name"], "why": why[0]})
    want = default_id(role, data, preview)
    default = want if any(o["id"] == want for o in opts) else (opts[0]["id"] if opts else "")
    return {"role": role, "options": opts, "default": default,
            "empty_reason": "" if opts else EMPTY.get(role, "Nothing set up yet."), "pending": pending}
