"""Subprocess adapter for the lip-sync scorer (fair SyncNet LSE-C / LSE-D), the injectable ``score`` of
:func:`opensoul.lipsync.run_rebuilt_method`.

The scorer is the lip-sync tool's own CLI, run in its own Python (never imported here: no torch in the app):

    <python> <cli> --score-only VIDEO [--ref RAW] --json   ->   {"lse_c": 6.1, "lse_d": 7.1, "method": "fair25", ...}

Config: ``presets/lipsync_scorer.json`` (cli, python, timeout_s), overridden by the env vars OPENSOUL_LIPSYNC_SCORER,
OPENSOUL_LIPSYNC_SCORER_PYTHON and OPENSOUL_LIPSYNC_SCORER_TIMEOUT. No cli configured = disabled
(:func:`enabled` is False and :func:`score` raises ``ScorerError('not_configured')``).

OPTIONAL EXTERNAL TOOL. The scoring CLI is NOT part of this repository and OpenSoul never downloads or installs
it; the shipped config is empty, so the scorer is off. :func:`opensoul.lipsync.run_rebuilt_method` (its only
user) is off the default lip-sync path too: the app, the nodes and the scripts never call it
(``tests/test_rebuilt_method_off_default.py``). Any CLI that honours the command line and JSON result above works.
Licensing, if a scorer is ever shipped or documented for download: the SyncNet model/code (syncnet_v2) is MIT, but
the S3FD face-detector weights it uses (``sfd_face.pth``) have no upstream licence, so they must never be
redistributed with OpenSoul or downloaded by default. See docs/LIPSYNC_SCORER.md."""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "presets" / "lipsync_scorer.json"
DEFAULT_TIMEOUT_S = 900.0
ENV_CLI, ENV_PY, ENV_TIMEOUT = "OPENSOUL_LIPSYNC_SCORER", "OPENSOUL_LIPSYNC_SCORER_PYTHON", "OPENSOUL_LIPSYNC_SCORER_TIMEOUT"


class ScorerError(RuntimeError):
    """``code``: not_configured | missing | no_video | timeout | failed | bad_output | no_face (lse_c null: SyncNet
    found no face; run_rebuilt_method keeps the a2v take and flags it, with no LatentSync fallback)."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ScorerConfig:
    cli: str = ""
    python: str = ""
    timeout_s: float = DEFAULT_TIMEOUT_S

    @property
    def enabled(self) -> bool:
        return bool(self.cli.strip())


def _resolve(p: str) -> str:
    """Absolute stays; a relative path (has a separator) is from the repo root; a bare name is looked up on PATH."""
    if not p:
        return ""
    q = Path(p).expanduser() if p.startswith("~") else Path(p)
    if q.is_absolute():
        return str(q)
    if "/" in p or os.sep in p:
        return str(ROOT / q)
    return shutil.which(p) or p


def load_config(path: Path | None = None, env: dict | None = None) -> ScorerConfig:
    env = os.environ if env is None else env
    data: dict = {}
    f = Path(path) if path else CONFIG
    if f.is_file():
        try:
            data = json.loads(f.read_text())
        except ValueError as e:
            raise ScorerError("not_configured", f"Lip-sync scorer config {f.name} isn't valid JSON: {e}") from e
    cli = (env.get(ENV_CLI) or data.get("cli") or "").strip()
    py = (env.get(ENV_PY) or data.get("python") or "").strip()
    raw_t = env.get(ENV_TIMEOUT) or data.get("timeout_s") or DEFAULT_TIMEOUT_S
    try:
        timeout = float(raw_t)
    except (TypeError, ValueError) as e:
        raise ScorerError("not_configured", f"Lip-sync scorer timeout {raw_t!r} isn't a number of seconds.") from e
    if timeout <= 0:
        raise ScorerError("not_configured", "Lip-sync scorer timeout must be more than 0 seconds.")
    return ScorerConfig(cli=_resolve(cli), python=_resolve(py), timeout_s=timeout)


def enabled(cfg: ScorerConfig | None = None) -> bool:
    try:
        return (cfg or load_config()).enabled
    except ScorerError:
        return False


def command(video, ref=None, cfg: ScorerConfig | None = None) -> list[str]:
    cfg = cfg or load_config()
    if not cfg.enabled:
        raise ScorerError("not_configured", f"The lip-sync scorer isn't set up (set {ENV_CLI} or 'cli' in "
                                            f"presets/lipsync_scorer.json).")
    cmd = ([cfg.python] if cfg.python else []) + [cfg.cli, "--score-only", str(video)]
    if ref:
        cmd += ["--ref", str(ref)]
    return cmd + ["--json"]


def parse_output(stdout: str) -> dict:
    """The scorer's JSON object: the last stdout line that parses as an object (log lines before it are fine),
    else the whole output. Needs a numeric lse_c."""
    text = (stdout or "").strip()
    found = None
    for chunk in [ln.strip() for ln in reversed(text.splitlines())] + [text]:
        if not (chunk.startswith("{") and chunk.endswith("}")):
            continue
        try:
            found = json.loads(chunk)
        except ValueError:
            try:
                found = ast.literal_eval(chunk)
            except (ValueError, SyntaxError):
                continue
        if isinstance(found, dict):
            break
        found = None
    if not isinstance(found, dict):
        raise ScorerError("bad_output", f"The lip-sync scorer printed no JSON result: {text[-300:]!r}")
    if "lse_c" in found and found["lse_c"] is None:
        raise ScorerError("no_face", f"The lip-sync scorer found no face to score (lse_c null): {found!r}")
    try:
        found["lse_c"] = float(found["lse_c"])
        if found.get("lse_d") is not None:
            found["lse_d"] = float(found["lse_d"])
    except (KeyError, TypeError, ValueError) as e:
        raise ScorerError("bad_output", f"The lip-sync scorer's result has no numeric lse_c: {found!r}") from e
    return found


def score(video, ref=None, cfg: ScorerConfig | None = None) -> dict:
    """Run the scorer on one take -> its result dict (lse_c, lse_d, method, ...). Raises ScorerError."""
    cfg = cfg or load_config()
    cmd = command(video, ref, cfg)
    if not Path(video).is_file():
        raise ScorerError("no_video", f"Can't score {Path(video).name}: the file isn't there.")
    for exe in ([cfg.python] if cfg.python else []) + [cfg.cli]:
        if not Path(exe).is_file():
            raise ScorerError("missing", f"The lip-sync scorer {exe} isn't there (check {ENV_CLI} / {ENV_PY}).")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=cfg.timeout_s, cwd=str(Path(cfg.cli).parent))
    except subprocess.TimeoutExpired as e:
        raise ScorerError("timeout", f"The lip-sync scorer took longer than {cfg.timeout_s:g} s on "
                                     f"{Path(video).name}.") from e
    except OSError as e:
        raise ScorerError("missing", f"The lip-sync scorer couldn't start: {e}") from e
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-300:]
        raise ScorerError("failed", f"The lip-sync scorer failed (exit {proc.returncode}) on {Path(video).name}: {tail}")
    return parse_output(proc.stdout)


def scorer(ref=None, cfg: ScorerConfig | None = None):
    """``take -> fair LSE-C`` for run_rebuilt_method (``ref`` = the raw take, passed as --ref)."""
    cfg = cfg or load_config()
    if not cfg.enabled:
        command("", cfg=cfg)  # raises not_configured with the setup hint

    def _score(take):
        return score(take, ref, cfg)["lse_c"]

    return _score
