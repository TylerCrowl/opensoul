"""Stage / model registry: load presets/models.yaml and report local install status.

Paths resolve via OPENSOUL_HOME (default ~/OpenSoul) and COMFY_DIR
(default $OPENSOUL_HOME/ComfyUI). No network calls — file existence only.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "presets" / "models.yaml"


def opensoul_home() -> Path:
    return Path(os.environ.get("OPENSOUL_HOME", Path.home() / "OpenSoul")).expanduser()


def comfy_dir() -> Path:
    return Path(os.environ.get("COMFY_DIR", opensoul_home() / "ComfyUI")).expanduser()


def comfy_models_dir() -> Path:
    return comfy_dir() / "models"


def _resolve_path(rel: str) -> Path:
    """Map a registry path to an absolute Path (local check only)."""
    if rel.startswith("$OPENSOUL_HOME/"):
        return opensoul_home() / rel[len("$OPENSOUL_HOME/") :]
    if rel.startswith("$HOME/"):
        return Path.home() / rel[len("$HOME/") :]
    # Relative to ComfyUI models/
    return comfy_models_dir() / rel


def _basename(rel: str) -> str:
    return Path(rel.replace("$OPENSOUL_HOME/", "").replace("$HOME/", "")).name


@lru_cache(maxsize=4)
def load_registry(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_REGISTRY
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("stages"), list):
        raise ValueError(f"models registry missing stages list: {p}")
    return data


def clear_registry_cache() -> None:
    load_registry.cache_clear()


def _default_backend_id(stage: dict[str, Any]) -> str:
    env_name = stage.get("env_backend")
    mapping = stage.get("env_backend_map") or {}
    if env_name and mapping:
        raw = (os.environ.get(env_name) or "").strip().lower()
        if raw in mapping:
            return mapping[raw]
    if env_name and not mapping:
        raw = (os.environ.get(env_name) or "").strip().lower()
        if raw:
            ids = {b.get("id") for b in stage.get("backends") or []}
            if raw in ids:
                return raw
    return stage.get("default_backend") or (stage.get("backends") or [{}])[0].get("id", "")


def _backend_by_id(stage: dict[str, Any], backend_id: str) -> dict[str, Any] | None:
    for b in stage.get("backends") or []:
        if b.get("id") == backend_id:
            return b
    return None


def _missing_files(files: list[str]) -> list[str]:
    missing: list[str] = []
    for rel in files or []:
        if not _resolve_path(rel).is_file():
            missing.append(_basename(rel))
    return missing


def _download_hint(stage: dict[str, Any], backend: dict[str, Any] | None = None) -> str:
    group = ""
    if backend and backend.get("download_group"):
        group = str(backend["download_group"]).strip()
    if not group:
        group = str(stage.get("download_group") or "").strip()
    if not group:
        return ""
    return f"./scripts/download_models.sh {group}"


def stage_status(registry_path: str | None = None) -> list[dict[str, Any]]:
    """Return one status dict per stage (local file checks only)."""
    data = load_registry(registry_path)
    out: list[dict[str, Any]] = []
    for stage in data["stages"]:
        stage_optional = bool(stage.get("optional"))
        default_id = _default_backend_id(stage)
        default_b = _backend_by_id(stage, default_id) or (stage.get("backends") or [{}])[0]
        default_files = list(default_b.get("files") or [])
        missing = _missing_files(default_files)
        backend_optional = bool(default_b.get("optional"))

        backends_info: list[dict[str, Any]] = []
        for b in stage.get("backends") or []:
            b_missing = _missing_files(list(b.get("files") or []))
            backends_info.append(
                {
                    "id": b.get("id"),
                    "label": b.get("label") or b.get("id"),
                    "license": b.get("license") or "",
                    "optional": bool(b.get("optional")),
                    "available": len(b_missing) == 0,
                    "missing_files": b_missing,
                }
            )

        if not missing:
            if stage_optional:
                status = "optional_installed"
            else:
                status = "installed"
        elif stage_optional or backend_optional:
            status = "optional_missing"
        else:
            status = "missing"

        hint = _download_hint(stage, default_b) if missing else ""
        out.append(
            {
                "id": stage.get("id"),
                "label": stage.get("label") or stage.get("id"),
                "default_backend": default_id,
                "status": status,
                "missing_files": missing,
                "download_hint": hint,
                "optional": stage_optional,
                "workflows": list(stage.get("workflows") or []),
                "backends": backends_info,
            }
        )
    return out


def health_lines(registry_path: str | None = None) -> list[dict[str, str]]:
    """Plain {label, value} rows for /api/health summary (one line per stage)."""
    lines: list[dict[str, str]] = []
    for s in stage_status(registry_path):
        label = s["label"]
        st = s["status"]
        if st in ("installed", "optional_installed"):
            value = "installed" if st == "installed" else "optional installed"
        elif st == "optional_missing":
            hint = s.get("download_hint") or ""
            value = f"optional missing — run {hint}" if hint else "optional missing"
        else:
            hint = s.get("download_hint") or ""
            value = f"missing — run {hint}" if hint else "missing"
        lines.append({"label": label, "value": value})
    return lines


# Stages the Advanced drawer offers a backend picker for (per-shot choice, same ids as
# OPENSOUL_TTS / OPENSOUL_LIPSYNC). The video variant is an install-time choice (LTX_VARIANT).
PICKER_STAGES = ("voice", "lipsync")


def backend_choices(registry_path: str | None = None, stage_ids: tuple[str, ...] = PICKER_STAGES) -> list[dict[str, Any]]:
    """Per-stage picker data: only backends whose files are present are offered.

    If nothing is installed for a stage, the default is still listed (``available: False``)
    so the picker never renders empty; the shot API refuses it outside preview mode.
    """
    by_id = {s["id"]: s for s in stage_status(registry_path)}
    out: list[dict[str, Any]] = []
    for sid in stage_ids:
        s = by_id.get(sid)
        if not s:
            continue
        opts = [{"id": b["id"], "label": b["label"], "license": b["license"], "available": True}
                for b in s["backends"] if b["available"]]
        if not opts:
            d = next((b for b in s["backends"] if b["id"] == s["default_backend"]), None)
            if d:
                opts.append({"id": d["id"], "label": d["label"], "license": d["license"], "available": False})
        default = s["default_backend"] if any(o["id"] == s["default_backend"] for o in opts) else opts[0]["id"] if opts else ""
        out.append({"stage": sid, "label": s["label"], "default": default, "options": opts,
                    "all_ids": [b["id"] for b in s["backends"]], "download_hint": s.get("download_hint") or ""})
    return out
