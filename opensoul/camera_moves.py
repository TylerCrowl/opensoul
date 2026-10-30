"""Stacked camera moves (camera_plan.md §4): up to 3 moves per shot, in order, prompt-only.

Rules live in presets/camera_rules.json so the server and the shot sheet use the same ones:
at most ``max_moves``; a move listed under ``alone`` can't be combined; no move twice; clashing moves
(push in + pull back, left + right, ...) are refused with a plain-English reason. One move keeps the
preset's own long prompt (bit-identical renders); a stack joins the presets' short ``phrase`` clauses."""
from __future__ import annotations

import json
from pathlib import Path

RULES_FILE = Path(__file__).resolve().parents[1] / "presets" / "camera_rules.json"


class MoveError(ValueError):
    """A camera stack that can't be rendered; the message is shown to the user as is."""


def rules() -> dict:
    return json.loads(RULES_FILE.read_text())


def _cams() -> dict[str, dict]:
    from opensoul.presets import load_presets

    return {c["id"]: c for c in load_presets()["camera"]}


def clash(a: str, b: str, r: dict | None = None) -> str | None:
    """Why moves ``a`` and ``b`` can't share a shot, or None."""
    r = r or rules()
    if a == b:
        return None
    for c in r["conflicts"]:
        if (a in c["a"] and b in c["b"]) or (b in c["a"] and a in c["b"]):
            return c["why"]
    return None


def check(moves: list[str] | None, cams: dict[str, dict] | None = None) -> list[str]:
    """Clean, validated list of move ids (``[]`` -> ``["static"]``). Raises MoveError."""
    cams = cams or _cams()
    r = rules()
    ids = [str(m or "").strip() for m in (moves or [])]
    ids = [m for m in ids if m] or ["static"]
    label = lambda m: cams[m]["label"] if m in cams else m  # noqa: E731
    for m in ids:
        if m not in cams:
            raise MoveError(f"Unknown camera move {m!r}.")
    if len(ids) > r["max_moves"]:
        raise MoveError(f"Up to {r['max_moves']} camera moves per shot.")
    if len(set(ids)) != len(ids):
        dup = next(m for m in ids if ids.count(m) > 1)
        raise MoveError(f"{label(dup)} is already in this shot.")
    if len(ids) > 1:
        for m in ids:
            if m in r["alone"]:
                raise MoveError(r["alone"][m])
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                why = clash(a, b, r)
                if why:
                    raise MoveError(why)
    return ids


def stack_prompt(moves: list[str], cams: dict[str, dict] | None = None) -> str:
    """One sentence with ordered timing, the shape LTX's prompting guide asks for. Single move: its own prompt."""
    cams = cams or _cams()
    ids = check(moves, cams)
    if len(ids) == 1:
        c = cams[ids[0]]
        return c.get("prompt", "")
    ph = [cams[m].get("phrase") or cams[m]["label"].lower() for m in ids]
    if len(ph) == 2:
        body = f"First {ph[0]}; then {ph[1]}"
    else:
        body = f"First {ph[0]}; then {ph[1]}; finally {ph[2]}"
    return f"{body}, ending with the subject centered and in sharp focus. One continuous shot, smooth transitions between the moves, no cuts."


MIN_SECONDS = {2: 5.0, 3: 7.0}   # camera_plan.md §4 rule 7: room for every move to read
DRAFT_MAX = 2                    # Draft clips are short (QUALITY["draft"] max 4 s), so two moves at most
DRAFT_WHY = "Drafts take up to 2 camera moves. Switch to Final for a third, or remove a move."
WORKFLOW_FRAMES = 169            # workflows/04 default length (~7 s at 24 fps) when a stage sets none


def min_seconds(moves: list[str] | None) -> float:
    n = len([m for m in (moves or []) if m and m != "static"])
    return MIN_SECONDS.get(min(n, 3), 0.0) if n > 1 else 0.0


def check_quality(moves: list[str] | None, quality: str) -> None:
    """Raises MoveError for a Draft with more than DRAFT_MAX moves."""
    if quality == "draft" and len([m for m in (moves or []) if m and m != "static"]) > DRAFT_MAX:
        raise MoveError(DRAFT_WHY)


def frames_for(seconds: float, fps: int = 24) -> int:
    """Smallest LTX frame count (8k+1) that lasts at least ``seconds``."""
    import math

    return 8 * max(1, math.ceil((float(seconds) * fps - 1) / 8)) + 1


def stretch_video(stage: dict, moves: list[str] | None, fps: int = 24) -> str | None:
    """Lengthen one video stage in place to the stack's minimum. Returns the note to show, or None."""
    need_s = min_seconds(moves)
    if not need_s or stage.get("stage") != "video":
        return None
    need = frames_for(need_s, int((stage.get("params") or {}).get("fps") or fps))
    lengths = [v["length"] for v in (stage.get("inputs") or {}).values() if isinstance(v, dict) and "length" in v]
    cur = stage.get("frames") or (max(lengths) if lengths else WORKFLOW_FRAMES)
    if stage.get("shape_voice"):  # a talking take sized to its voice keeps this minimum (opensoul.voice_shape)
        stage["min_frames"] = max(int(stage.get("min_frames") or 0), need)
    if cur >= need:
        return None
    for v in (stage.get("inputs") or {}).values():
        if isinstance(v, dict):
            if "length" in v:
                v["length"] = need
            if "frames_number" in v:
                v["frames_number"] = need
    if "frames" in stage:
        stage["frames"] = need
    if "pad_audio_to_s" in stage:
        stage["pad_audio_to_s"] = round(need / fps, 4)  # the voice is padded with silence to the longer clip
    stage.setdefault("params", {}).update({"frames": need, "duration_s": round(need / fps, 3)})
    n = len([m for m in moves if m and m != "static"])
    return f"Lengthened to {need_s:g} s for {n} moves."


def experimental(moves: list[str], cams: dict[str, dict] | None = None) -> bool:
    """Any experimental move, or any stack (stacks are not checked on the GPU yet, camera_plan.md §5)."""
    cams = cams or _cams()
    return len(moves) > 1 or any(cams.get(m, {}).get("experimental") for m in moves)


def label(moves: list[str], cams: dict[str, dict] | None = None) -> str:
    cams = cams or _cams()
    return " → ".join(cams[m]["label"] if m in cams else m for m in moves)
