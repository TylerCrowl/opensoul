"""OS-025: a short drop of the studio link does not fail the take; OpenSoul waits and collects the result."""
from __future__ import annotations

import pytest

from opensoul import comfy_client as C


class ReadTimeout(Exception):
    pass


def test_reconnecting_retries_link_errors_then_succeeds():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ReadTimeout("timed out")
        return "ok"
    assert C._reconnecting(fn, "render", budget_s=60, sleep=lambda s: None) == "ok"
    assert calls["n"] == 3


def test_reconnecting_gives_a_plain_message_after_the_budget():
    def fn():
        raise ConnectionError("refused")
    with pytest.raises(RuntimeError, match="Lost the studio connection"):
        C._reconnecting(fn, "render", budget_s=0, sleep=lambda s: None)


def test_a_failed_job_is_not_retried():
    def fn():
        raise ValueError("bad workflow")
    with pytest.raises(ValueError):
        C._reconnecting(fn, "render", budget_s=60, sleep=lambda s: None)


def test_wait_survives_a_drop():
    class Job:
        n = 0
        status = "succeeded"

        def result(self):
            Job.n += 1
            if Job.n == 1:
                raise ConnectionResetError("reset")
            return self
    C._reconnecting(Job().result, "render", budget_s=30, sleep=lambda s: None)
    assert Job.n == 2


def test_zimage_history_poll_survives_a_drop(tmp_path):
    import urllib.error

    from opensoul import zimage_master as Z

    state = {"n": 0}

    def http(method, url, body):
        if method == "POST":
            return {"prompt_id": "p1"}
        state["n"] += 1
        if state["n"] == 1:
            raise urllib.error.URLError("timed out")
        return {"p1": {"status": {"completed": True}, "outputs": {Z.N_SAVE: {"images": [{"filename": "a.png"}]}}}}
    out = Z.run("x", 1, tmp_path / "m.png", cfg={"timeout_s": 60}, base_url="http://s", http=http,
                fetch=lambda u: b"png", sleep=lambda s: None)
    assert out.read_bytes() == b"png" and state["n"] == 2


def test_wait_notes_queue_and_render_time():  # OS-041
    seq = iter(["queued", "queued", "running", "running", "succeeded"])
    clock = {"t": 100.0}

    class Job:
        id = "j1"
        status = "queued"

        def refresh(self):
            self.status = next(seq)
            clock["t"] += 10
            return self
    import time as _t

    real = _t.time
    _t.time = lambda: clock["t"]
    try:
        C._wait(Job(), sleep=lambda s: None)
    finally:
        _t.time = real
    t = C.last_timing()
    assert t == {"queue_s": 30.0, "run_s": 20.0}


def test_wait_raises_job_failed():
    from comfy_sdk.exceptions import JobFailed

    class Job:
        id = "j2"
        status = "running"

        def refresh(self):
            self.status = "failed"
            return self
    with pytest.raises(JobFailed):
        C._wait(Job(), sleep=lambda s: None)


def test_card_time_is_render_time_not_queue():
    from types import SimpleNamespace

    from app.storyboard_api import _render_times

    res = SimpleNamespace(seconds=300.0, steps=[{"stage": "voice"}, {"stage": "video", "secs": 280.0, "queue_s": 160.0, "run_s": 120.0}])
    t = _render_times(res)
    assert t["render_seconds"] == 140.0 and t["queue_seconds"] == 160.0 and t["wall_seconds"] == 300.0
    assert _render_times(SimpleNamespace(seconds=50.0, steps=[{"stage": "video", "secs": 50.0}])) == {"render_seconds": 50.0}
