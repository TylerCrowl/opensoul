#!/usr/bin/env bash
# CPU-friendly dev install (agent box / laptop without GPU).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
command -v python3 >/dev/null || { echo "ERROR: python3 (>= 3.10) is required" >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "ERROR: Python >= 3.10 is required (found $(python3 -V))" >&2; exit 1; }
python3 -m venv .venv || { echo "ERROR: could not create a venv. On Debian/Ubuntu: sudo apt install python3-venv" >&2; exit 1; }
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip
if command -v ffmpeg >/dev/null; then
  pip install -e ".[dev]"
else
  echo "NOTE: no system ffmpeg; installing the static imageio-ffmpeg build into the venv (or: apt install ffmpeg / brew install ffmpeg)" >&2
  pip install -e ".[dev,ffmpeg]"
fi
export OPENSOUL_DRY_RUN=1
pytest -q
python scripts/check_workflows.py
echo "OK — run: source .venv/bin/activate && OPENSOUL_DRY_RUN=1 OPENSOUL_DEMO_CAST=1 opensoul-ui   # http://127.0.0.1:7860 (OPENSOUL_PORT to change)"
