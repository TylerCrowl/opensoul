"""Best of N: render one thing with N seeds, keep every result, pick one.

Generic, standard library only, so any step can use it (the master step does; lip-sync takes, sheets, stills and
plates can adopt it later). The caller supplies ``render(seed, out_path) -> Path``; this module runs the seeds one
after another, keeps all the files, and writes one record:

    {"kind": "master", "n": 4, "seeds": [33, 34, 35, 36],
     "candidates": [{"seed": 33, "file": "option_33.png", "state": "done", "score": None, "reject": ""}, ...],
     "pick": {"seed": 34, "file": "option_34.png", "by": "user"} | None}

A pick is manual (``pick``) unless a scorer is given, then ``auto_pick`` takes the best-scoring candidate that has no
reject reason. Nothing is ever deleted: the candidates that weren't picked stay where they were rendered."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

RenderFn = Callable[[int, Path], Path]
# scorer(path) -> (score or None, reject reason or ""); higher is better
ScoreFn = Callable[[Path], "tuple[float | None, str]"]
MAX_N = 8


class Cancelled(RuntimeError):
    pass


def seeds(start: int, n: int) -> list[int]:
    """n consecutive seeds from ``start`` (1..MAX_N of them)."""
    n = max(1, min(MAX_N, int(n)))
    return [int(start) + i for i in range(n)]


def new_record(kind: str, seed_list: list[int], name: str = "option", ext: str = ".png") -> dict:
    return {"kind": kind, "n": len(seed_list), "seeds": list(seed_list), "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "candidates": [{"seed": s, "file": f"{name}_{s}{ext}", "state": "queued", "score": None, "reject": ""}
                           for s in seed_list],
            "pick": None}


def run(record: dict, out_dir: str | Path, render: RenderFn, *, scorer: Optional[ScoreFn] = None,
        should_cancel: Optional[Callable[[], bool]] = None, on_change: Optional[Callable[[dict], None]] = None) -> dict:
    """Render every queued candidate in turn (one at a time). A failed seed records its error and the rest go on;
    a cancel stops before the next seed (already-drawn candidates are kept). With a scorer, auto-picks at the end."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for c in record["candidates"]:
        if c["state"] != "queued":
            continue
        if should_cancel and should_cancel():
            c["state"] = "cancelled"
            for rest in record["candidates"]:
                if rest["state"] == "queued":
                    rest["state"] = "cancelled"
            break
        c["state"] = "running"
        if on_change:
            on_change(record)
        try:
            render(int(c["seed"]), out / c["file"])
            c["state"] = "done"
            if scorer:
                score, why = scorer(out / c["file"])
                c["score"], c["reject"] = (None if score is None else float(score)), str(why or "")
        except Cancelled:
            c["state"] = "cancelled"
        except Exception as e:  # noqa: BLE001 - one bad seed doesn't lose the others
            c["state"], c["error"] = "error", str(e)[:300]
        if on_change:
            on_change(record)
    if scorer and record.get("pick") is None:
        auto_pick(record)
    return record


def done(record: dict) -> list[dict]:
    return [c for c in record["candidates"] if c["state"] == "done"]


def pick(record: dict, seed: int, by: str = "user") -> dict:
    """Mark one finished candidate as the pick (the others stay on disk and in the record)."""
    c = next((x for x in done(record) if int(x["seed"]) == int(seed)), None)
    if c is None:
        raise ValueError(f"no finished option with seed {seed}")
    record["pick"] = {"seed": int(c["seed"]), "file": c["file"], "by": by, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    return record


def auto_pick(record: dict) -> dict | None:
    """The best-scoring finished candidate without a reject reason ("by": "score"), or None (then the user picks)."""
    ok = [c for c in done(record) if c.get("score") is not None and not c.get("reject")]
    if not ok:
        return None
    best = max(ok, key=lambda c: c["score"])
    pick(record, best["seed"], by="score")
    return best


def save(record: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return p


def load(path: str | Path) -> dict[str, Any] | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
