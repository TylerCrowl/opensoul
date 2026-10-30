"""cancel_own_prompt only ever touches our own prompt (mocked HTTP, no network),
and no code in the repo sends a bare, global ComfyUI interrupt."""

import re
from pathlib import Path

import pytest

from opensoul import comfy_cancel
from opensoul.comfy_cancel import cancel_own_prompt

BASE = "http://comfy.invalid:8188"
OURS = "our-prompt-id"
OTHER = "someone-elses-prompt"


class FakeComfy:
    def __init__(self, running=(), pending=()):
        self.queue = {
            "queue_running": [[i, pid, {}, {}, []] for i, pid in enumerate(running)],
            "queue_pending": [[i + 10, pid, {}, {}, []] for i, pid in enumerate(pending)],
        }
        self.calls = []

    def __call__(self, method, url, body=None):
        self.calls.append((method, url, body))
        if method == "GET" and url == BASE + "/queue":
            return self.queue
        return {}

    def posts(self, path):
        return [c for c in self.calls if c[0] == "POST" and c[1] == BASE + path]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("real network used in a test")

    monkeypatch.setattr(comfy_cancel, "_default_http", boom)
    monkeypatch.setattr(comfy_cancel.urllib.request, "urlopen", boom)


def test_pending_prompt_is_deleted_from_queue_not_interrupted():
    http = FakeComfy(running=[OTHER], pending=[OURS])
    assert cancel_own_prompt(BASE, OURS, http=http) == "deleted"
    assert http.posts("/queue") == [("POST", BASE + "/queue", {"delete": [OURS]})]
    assert http.posts("/interrupt") == []


def test_running_prompt_is_interrupted_by_id():
    http = FakeComfy(running=[OURS], pending=[OTHER])
    assert cancel_own_prompt(BASE + "/", OURS, http=http) == "interrupted"
    assert http.posts("/interrupt") == [("POST", BASE + "/interrupt", {"prompt_id": OURS})]
    assert http.posts("/queue") == []


def test_running_prompt_that_finishes_before_interrupt_is_left_alone():
    """Ours is running at the first GET /queue but gone by the re-check: no interrupt."""
    http = FakeComfy(running=[OURS])
    first = http.queue
    states = iter([first, {"queue_running": [[1, OTHER, {}, {}, []]], "queue_pending": []}])

    def seq(method, url, body=None):
        http.calls.append((method, url, body))
        return next(states) if method == "GET" else {}

    assert cancel_own_prompt(BASE, OURS, http=seq) == "finished_before_interrupt"
    assert http.posts("/interrupt") == [] and http.posts("/queue") == []
    assert [c[0] for c in http.calls] == ["GET", "GET"]


def test_running_prompt_no_longer_first_is_not_interrupted():
    http = FakeComfy(running=[OTHER, OURS])
    assert cancel_own_prompt(BASE, OURS, http=http) == "finished_before_interrupt"
    assert http.posts("/interrupt") == []


def test_other_prompt_running_means_no_interrupt_and_no_delete():
    http = FakeComfy(running=[OTHER])
    assert cancel_own_prompt(BASE, OURS, http=http) == "noop"
    assert http.posts("/interrupt") == [] and http.posts("/queue") == []


def test_prompt_not_found_is_a_noop():
    http = FakeComfy()
    assert cancel_own_prompt(BASE, OURS, http=http) == "noop"
    assert [c for c in http.calls if c[0] != "GET"] == []


def test_unreadable_queue_never_falls_back_to_global_interrupt():
    calls = []

    def http(method, url, body=None):
        calls.append((method, url, body))
        raise OSError("connection refused")

    assert cancel_own_prompt(BASE, OURS, http=http) == "error"
    assert [c for c in calls if c[0] == "POST"] == []


# --- repo-wide guard ------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
HELPER = REPO / "opensoul" / "comfy_cancel.py"
THIS = Path(__file__).resolve()
CODE_EXT = {".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "cvenv", "__pycache__", "opensoul.egg-info"}
# A ComfyUI interrupt endpoint (curl / urllib / fetch / f-string URL) or an SDK-style .interrupt() call.
BARE = re.compile(r"/interrupt\b|\.interrupt\s*\(")


def _code_files():
    for p in REPO.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(REPO).parts):
            continue
        if p.is_file() and p.suffix in CODE_EXT and p.resolve() not in (HELPER, THIS):
            yield p


def test_no_bare_global_interrupt_left_in_repo():
    hits = []
    for p in _code_files():
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if BARE.search(line):
                hits.append(f"{p.relative_to(REPO)}:{n}: {line.strip()}")
    assert not hits, "bare ComfyUI interrupt; use opensoul.comfy_cancel.cancel_own_prompt:\n" + "\n".join(hits)

