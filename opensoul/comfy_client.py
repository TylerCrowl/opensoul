"""Every GPU stage of OpenSoul runs through the official Comfy SDK (``comfy-sdk``).

The SDK speaks Comfy API v2. The same code targets:

* self-hosted ComfyUI behind Comfy's ``comfy-api-proxy`` (default here)::

      comfy-api-proxy --comfyui http://127.0.0.1:8188 --port 8189
      export COMFY_BASE_URL=http://127.0.0.1:8189

* a Comfy API deployment or Comfy Cloud (set ``COMFY_BASE_URL`` and ``COMFY_API_KEY``).

We stay on local open-weights workflows: no partner/API nodes, no Router models.
See docs/COMFY_PLATFORM.md.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("opensoul.comfy")

DEFAULT_BASE_URL = "http://127.0.0.1:8189"


class ComfyNotConfiguredError(RuntimeError):
    pass


def base_url() -> str:
    return (os.environ.get("COMFY_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")


def api_key() -> str | None:
    return (os.environ.get("COMFY_API_KEY") or "").strip() or None


def make_client():
    """Construct a ``comfy_sdk.Comfy`` client. Import is lazy so CPU tests need no Comfy.

    comfy-sdk defaults to Comfy Cloud when ``COMFY_BASE_URL`` is unset, so we pin it to
    our default (the local proxy) before constructing the client.
    """
    try:
        from comfy_sdk import Comfy
    except ImportError as e:  # pragma: no cover
        raise ComfyNotConfiguredError("comfy-sdk is not installed. pip install 'comfy-sdk>=0.5'") from e

    os.environ["COMFY_BASE_URL"] = base_url()
    key = api_key()
    return Comfy(api_key=key, client_info="opensoul") if key else Comfy(client_info="opensoul")


def load_graph(workflow_path: str | Path) -> dict:
    return json.loads(Path(workflow_path).read_text())


def apply_inputs(graph: dict, inputs: dict[str, dict[str, Any]]) -> None:
    """Validate that every override names an existing node and input (catches silent typos)."""
    for node_id, mapping in inputs.items():
        node = graph.get(str(node_id))
        if node is None:
            raise KeyError(f"workflow has no node {node_id!r}")
        for name in mapping:
            if name not in node.get("inputs", {}):
                raise KeyError(f"node {node_id} ({node['class_type']}) has no input {name!r}")


def _is_existing_file(value: Any) -> bool:
    """True if ``value`` names an existing file. Long prompt strings (> NAME_MAX) must not raise."""
    if not isinstance(value, (str, Path)):
        return False
    try:
        return Path(value).is_file()
    except (OSError, ValueError):
        return False


def run_workflow_file(
    workflow_path: str | Path,
    *,
    inputs: dict[str, dict[str, Any]] | None = None,
    output_node_id: str = "9",
    out_dir: str | Path = "outputs",
    metadata: dict[str, str] | None = None,  # local comfy-api-proxy 422s on label maps; callers pass None
) -> list[Path]:
    """Run an API-format workflow through the Comfy SDK and save one node's outputs.

    ``inputs`` maps node_id -> {input_name: value_or_file_path}. Existing file paths are
    uploaded with ``client.assets.from_file`` and passed as ``core/ASSET`` references.
    """
    inputs = inputs or {}
    apply_inputs(load_graph(workflow_path), inputs)
    client = make_client()
    wf = client.workflows.from_file(str(workflow_path))
    for node_id, mapping in inputs.items():
        for name, value in mapping.items():
            if _is_existing_file(value):
                value = client.assets.from_file(str(value))
            wf.set_input(str(node_id), name, value)

    t0 = time.time()
    log.info("comfy_sdk submit %s -> %s", Path(workflow_path).name, base_url())
    job = _submit(client, wf, metadata)
    log.info("comfy_sdk job id=%s", getattr(job, "id", "?"))
    _wait(job)
    log.info("comfy_sdk job %s finished status=%s in %.1fs", getattr(job, "id", "?"), job.status, time.time() - t0)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return _reconnecting(lambda: _save_outputs(job, output_node_id, out_dir), "download")


def _save_outputs(job, output_node_id: str, out_dir: Path) -> list[Path]:
    saved: list[Path] = []
    for output in job.outputs:
        log.info("comfy_sdk job output node=%s type=%s name=%s", output.node_id, output.type, output.name)
        if output.type == "text":  # e.g. the identity gate's JSON report
            try:
                text = output.to_bytes().decode("utf-8", "replace")
                log.info("comfy_sdk text output node=%s: %s", output.node_id, text[:2000])
                (out_dir / f"node{output.node_id}_report.txt").write_text(text)
            except Exception as e:  # pragma: no cover - depends on server support
                log.warning("could not fetch text output: %s", e)
    for output in job.get_outputs(str(output_node_id)):
        dest = out_dir / output.name
        output.to_file(str(dest))
        saved.append(dest)
        log.info("comfy_sdk output node=%s -> %s", output_node_id, dest)
    return saved


# ---------------------------------------------------------------- a short drop of the studio link (OS-025)
# The studio keeps rendering when the link to it drops for a moment. OpenSoul keeps the job id, waits for the link to
# come back and collects the result, instead of failing the take with "timed out".
RECONNECT_S = float(os.environ.get("OPENSOUL_STUDIO_RECONNECT_S", "900") or 900)
LOST_MSG = ("Lost the studio connection for {mins} min. The studio may still finish this take. "
            "Check the studio and the network. Then click Regenerate.")


def _is_link_error(e: BaseException) -> bool:
    """True for a transport problem (no answer, connection reset, read timeout, 502/503/504 from a proxy), never for
    a job that failed or a workflow the studio refused."""
    name = type(e).__name__
    try:
        from comfy_sdk.exceptions import InvalidWorkflow, JobFailed, MissingAsset, NotFound

        if isinstance(e, (JobFailed, InvalidWorkflow, MissingAsset, NotFound)):
            return False
    except ImportError:  # pragma: no cover
        pass
    if isinstance(e, (ConnectionError, TimeoutError, OSError)):
        return True
    if name in {"ConnectError", "ConnectTimeout", "ReadTimeout", "ReadError", "WriteError", "WriteTimeout",
                "PoolTimeout", "RemoteProtocolError", "TransportError", "NetworkError", "TimeoutException"}:
        return True
    status = getattr(e, "status_code", None) or getattr(e, "status", None)
    if status in (502, 503, 504):
        return True
    return "timed out" in str(e).lower() or "connection" in str(e).lower() and "refused" in str(e).lower()


def _reconnecting(fn, what: str, budget_s: float | None = None, sleep=time.sleep):
    """Run fn(); on a link error, wait and try again until budget_s runs out."""
    budget = RECONNECT_S if budget_s is None else budget_s
    t0 = time.monotonic()
    delay = 2.0
    while True:
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if not _is_link_error(e):
                raise
            waited = time.monotonic() - t0
            if waited >= budget:
                raise RuntimeError(LOST_MSG.format(mins=max(1, round(budget / 60)))) from e
            log.warning("studio link lost during %s (%s: %s); retrying in %.0fs", what, type(e).__name__, e, delay)
            sleep(delay)
            delay = min(delay * 1.6, 20.0)


def _submit(client, wf, metadata):
    """Submit once per idempotency key: a resend after a drop can't make a second job on the studio."""
    import uuid

    key = f"opensoul-{uuid.uuid4().hex}"

    def go():
        try:
            return (client.submit(wf, metadata=metadata, idempotency_key=key) if metadata
                    else client.submit(wf, idempotency_key=key))
        except TypeError:  # an older comfy-sdk without idempotency_key
            return client.submit(wf, metadata=metadata) if metadata else client.submit(wf)
    try:
        return _reconnecting(go, "submit", budget_s=min(RECONNECT_S, 120.0))
    except Exception as e:  # noqa: BLE001
        if type(e).__name__ == "IdempotencyKeyReuse":  # the first try reached the studio; never send it twice
            raise RuntimeError("The studio got this take, but the link dropped before it said so. Check the studio "
                               "queue. Then click Regenerate if the take does not appear.") from e
        raise


# OS-041: how long the last job of this thread waited in the studio queue and how long it ran. Wall time mixes the two,
# so a take card said "4.8 min" for a 2 min render behind 3 other jobs.
TIMING = threading.local()
RUNNING = {"running", "in_progress", "executing", "processing", "started"}


def last_timing() -> dict[str, float]:
    """{"queue_s", "run_s"} of this thread's last studio job ({} when unknown)."""
    return dict(getattr(TIMING, "last", {}) or {})


def _wait(job, sleep=time.sleep) -> None:
    """Poll the job to the end (like job.result()), noting when it leaves the queue. A dropped link means 'wait and
    poll again', not 'failed'."""
    t_sub = time.time()
    seen = {"run": None}
    TIMING.last = {}

    def poll():
        delay = 0.5
        while True:
            job.refresh()
            st = str(job.status)
            if seen["run"] is None and st in RUNNING:
                seen["run"] = time.time()
            if st in ("succeeded", "canceled", "failed", "expired"):
                return st
            sleep(delay)
            delay = min(delay * 1.5, 5.0)

    if not hasattr(job, "refresh"):  # an older SDK or a test double: no polling hook
        _reconnecting(job.result, "render")
        return
    st = _reconnecting(poll, "render")
    t_end = time.time()
    if seen["run"] is not None:
        TIMING.last = {"queue_s": round(seen["run"] - t_sub, 1), "run_s": round(t_end - seen["run"], 1)}
    if st != "succeeded":
        from comfy_sdk.exceptions import JobFailed

        err = getattr(job, "error", None)
        why = str(getattr(err, "message", "") or "").strip().splitlines()
        # OS-055: the take shows the studio's own reason (a missing node or voice file), not only 'ended failed'
        raise JobFailed(f"job {getattr(job, 'id', '?')} ended {st}" + (f": {why[-1][:300]}" if why else ""), error=err)


def sdk_status() -> dict[str, Any]:
    """Non-throwing status for the UI / health checks."""
    info: dict[str, Any] = {
        "COMFY_BASE_URL": base_url(),
        "has_api_key": bool(api_key()),
        "comfy_sdk_importable": False,
        "version": None,
        "note": "Local open weights: ComfyUI on :8188 + `comfy-api-proxy` on :8189 (COMFY_BASE_URL).",
    }
    try:
        import comfy_sdk

        info["comfy_sdk_importable"] = True
        info["version"] = getattr(comfy_sdk, "__version__", "unknown")
    except ImportError:
        info["note"] = "pip install comfy-sdk>=0.5"
    return info
