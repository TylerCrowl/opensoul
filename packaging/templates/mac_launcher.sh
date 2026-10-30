#!/bin/bash
# OpenSoul.app: copies its private Python + app to ~/Library/Application Support/OpenSoul the first time
# (so it runs from a normal, writable folder), offers once to move the app into Applications when it was opened
# from Downloads (opensoul/mac_move.py; it asks, never moves on its own), then starts OpenSoul in its own window
# (opensoul/launcher.py + opensoul/desktop_window.py; the browser if the window can't open).
# Nothing is installed system-wide; no admin password; no network settings are touched.
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
APP="$(cd "$(dirname "$0")/../.." && pwd)"
VER="$(tr -d '[:space:]' < "$RES/VERSION")"
SUP="$HOME/Library/Application Support/OpenSoul"
RT="$SUP/runtime/$VER"
mkdir -p "$SUP/logs"
LOG="$SUP/logs/launcher.log"
exec >>"$LOG" 2>&1
echo "--- $(date) OpenSoul $VER"

fail() {
  /usr/bin/osascript -e "display alert \"OpenSoul couldn't start\" message \"$1

Details are in: $LOG\"" >/dev/null 2>&1
  exit 1
}

if [ "@ARCH@" = "arm64" ] && [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null)" != "1" ]; then
  fail "This copy of OpenSoul is for Macs with Apple chips (M1 or newer). Ask for the Intel version."
fi

if [ ! -f "$RT/.ready" ]; then
  /usr/bin/osascript -e 'display notification "Getting ready. This takes about a minute, only the first time." with title "OpenSoul"' >/dev/null 2>&1 &
  mkdir -p "$SUP/runtime" || fail "Couldn't create $SUP."
  rm -rf "$RT.partial"
  /usr/bin/ditto "$RES/runtime" "$RT.partial" || fail "Couldn't copy OpenSoul's files. Is the disk full?"
  # The copy is OpenSoul's own files; clear the download flag on them so its private Python may run.
  /usr/bin/xattr -dr com.apple.quarantine "$RT.partial" 2>/dev/null || true
  mv "$RT.partial" "$RT" && touch "$RT/.ready" || fail "Couldn't finish setting up in $SUP."
fi

cd "$RT/app" || fail "OpenSoul's files are missing in $RT."
# Opened from Downloads? Ask once whether to move OpenSoul into Applications. Exit code 3: moved, and the moved copy
# is opening now, so this one stops here.
"$RT/python/bin/python3" -I -m opensoul.mac_move "$APP"
[ $? -eq 3 ] && exit 0
# exec: Python takes over this process, so macOS shows it as OpenSoul (this bundle's name and icon) in the Dock.
export OPENSOUL_APP=mac OPENSOUL_APP_ICON="$RES/OpenSoul.icns"
exec "$RT/python/bin/python3" -I -m opensoul.launcher open
