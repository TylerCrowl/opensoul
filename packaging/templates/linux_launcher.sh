#!/usr/bin/env bash
# OpenSoul for Linux: runs its private Python from this folder, starts OpenSoul in the background and opens the
# browser (opensoul/launcher.py). Nothing is installed system-wide and no sudo is needed.
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
if [ "$(uname -m)" != "@ARCH@" ]; then
  echo "This copy of OpenSoul is for @ARCH@ computers; this one is $(uname -m)." >&2
  exit 1
fi
cd "$HERE/runtime/app" || exit 1
exec "$HERE/runtime/python/bin/python3" -I -m opensoul.launcher "${@:-open}"
