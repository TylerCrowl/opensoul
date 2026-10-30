"""Cancel only *our own* ComfyUI prompt, never someone else's.

The ComfyUI on the Spark is shared. A bare ``POST /interrupt`` stops whatever is
running right now, which may be another user's render. Use
``cancel_own_prompt(base_url, prompt_id)`` instead:

* our prompt is still pending  -> ``POST /queue {"delete": [prompt_id]}`` (no interrupt)
* our prompt is the running one -> ``POST /interrupt {"prompt_id": prompt_id}``
  (newer ComfyUI only interrupts that prompt; older ComfyUI ignores the body,
  which is why we only call it after confirming our prompt is the running one)
* anything else (another prompt running, ours finished/unknown, queue unreadable)
  -> do nothing

Right before the interrupt we read ``/queue`` again and only interrupt if our prompt
is *still* ``queue_running[0]``. If it finished in between we return
``"finished_before_interrupt"`` and send nothing, so an older ComfyUI that ignores
the body can't stop the next tenant's prompt.

Standard library only, so Spark-side runner scripts can load this file directly
(importlib by path) without importing the rest of the ``opensoul`` package.
This is the only place in the repo allowed to call ``/interrupt``
(``tests/test_comfy_cancel.py`` enforces that).
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Optional

# http(method, url, json_body_or_None) -> parsed JSON (or None)
HttpFn = Callable[[str, str, Optional[dict]], Any]

PENDING_DELETED = "deleted"
RUNNING_INTERRUPTED = "interrupted"
FINISHED_BEFORE_INTERRUPT = "finished_before_interrupt"
NOOP = "noop"
ERROR = "error"


def _default_http(method: str, url: str, body: Optional[dict] = None, timeout: float = 30) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    raw = urllib.request.urlopen(r, timeout=timeout).read()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _ids(entries: Any) -> list[str]:
    """queue_running / queue_pending entries look like [number, prompt_id, prompt, ...]."""
    out = []
    for e in entries or []:
        if isinstance(e, (list, tuple)) and len(e) > 1:
            out.append(str(e[1]))
    return out


def cancel_own_prompt(base_url: str, prompt_id: str, http: Optional[HttpFn] = None) -> str:
    """Cancel ``prompt_id`` on the ComfyUI at ``base_url`` without touching other prompts.

    Returns ``"deleted"``, ``"interrupted"``, ``"finished_before_interrupt"``,
    ``"noop"`` or ``"error"``. Never raises
    and never falls back to a global interrupt.
    """
    if not prompt_id:
        return NOOP
    http = http or _default_http
    base = base_url.rstrip("/")
    pid = str(prompt_id)
    try:
        q = http("GET", base + "/queue", None) or {}
    except Exception:
        return ERROR
    if not isinstance(q, dict):
        return ERROR
    try:
        if pid in _ids(q.get("queue_pending")):
            http("POST", base + "/queue", {"delete": [pid]})
            return PENDING_DELETED
        if pid in _ids(q.get("queue_running")):
            # Fresh look immediately before interrupting: still ours, still first?
            q2 = http("GET", base + "/queue", None) or {}
            running = _ids(q2.get("queue_running")) if isinstance(q2, dict) else []
            if not running or running[0] != pid:
                return FINISHED_BEFORE_INTERRUPT
            http("POST", base + "/interrupt", {"prompt_id": pid})
            return RUNNING_INTERRUPTED
    except Exception:
        return ERROR
    return NOOP
