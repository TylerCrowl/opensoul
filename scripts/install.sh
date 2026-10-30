#!/usr/bin/env bash
# One-line install of the OpenSoul desktop package for macOS and Linux (current user only, no sudo).
#
#   ./scripts/install.sh OpenSoul-<ver>-mac-arm64.zip           # from a package you already have
#   ./scripts/install.sh https://<releases>/OpenSoul-<ver>-linux-x64.tar.gz
#   curl -fsSL <raw-url>/scripts/install.sh | OPENSOUL_RELEASE_BASE=<releases-url> bash
#
# Picks the package for this computer (mac-arm64, mac-x64, linux-x64, linux-arm64), puts it in ~/Applications
# (Mac) or ~/.local/opt/OpenSoul (Linux), adds a menu entry on Linux and opens OpenSoul. It never asks for an admin
# password and changes no system, network or firewall settings. Packages are built by packaging/build_bundle.py.
set -euo pipefail

say() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf 'OpenSoul install: %s\n' "$*" >&2; exit 1; }

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) TARGET=mac-arm64 EXT=zip ;;
  Darwin-x86_64) TARGET=mac-x64 EXT=zip ;;
  Linux-x86_64) TARGET=linux-x64 EXT=tar.gz ;;
  Linux-aarch64|Linux-arm64) TARGET=linux-arm64 EXT=tar.gz ;;
  *) die "no package for $(uname -s) $(uname -m) yet; see docs/DESKTOP.md to run from source." ;;
esac

SRC="${1:-}"
if [ -z "$SRC" ]; then
  BASE="${OPENSOUL_RELEASE_BASE:-}"
  [ -n "$BASE" ] || die "give a package file or URL, or set OPENSOUL_RELEASE_BASE to the releases download folder."
  SRC="${BASE%/}/OpenSoul-latest-$TARGET.$EXT"
fi
case "$SRC" in
  *"$TARGET"*) ;;
  *) die "$SRC isn't the $TARGET package this computer needs." ;;
esac

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
PKG="$TMP/pkg.$EXT"
if [ -f "$SRC" ]; then
  cp "$SRC" "$PKG"
else
  say "Downloading $SRC"
  curl -fL --progress-bar -o "$PKG" "$SRC" || die "download failed."
fi
if [ -f "${SRC%.*}.json" ] && command -v python3 >/dev/null; then  # the builder's manifest next to a local package
  WANT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "${SRC%.*}.json" 2>/dev/null || true)"
  [ -n "$WANT" ] && { GOT="$( (shasum -a 256 "$PKG" 2>/dev/null || sha256sum "$PKG") | cut -d' ' -f1)"; [ "$GOT" = "$WANT" ] || die "checksum mismatch."; }
fi

if [ "$TARGET" = mac-arm64 ] || [ "$TARGET" = mac-x64 ]; then
  DEST="$HOME/Applications"
  mkdir -p "$DEST"
  /usr/bin/ditto -x -k "$PKG" "$TMP/x"
  rm -rf "$DEST/OpenSoul.app"
  mv "$TMP/x/OpenSoul.app" "$DEST/OpenSoul.app"
  # You chose to install it from Terminal, so skip the one-time "unidentified developer" prompt for this app only.
  /usr/bin/xattr -dr com.apple.quarantine "$DEST/OpenSoul.app" 2>/dev/null || true
  say "Installed $DEST/OpenSoul.app"
  [ "${OPENSOUL_NO_OPEN:-}" = 1 ] || open "$DEST/OpenSoul.app"
else
  DEST="${OPENSOUL_INSTALL_DIR:-$HOME/.local/opt}"
  mkdir -p "$DEST"
  tar -xzf "$PKG" -C "$TMP"
  rm -rf "$DEST/OpenSoul"
  mv "$TMP/OpenSoul" "$DEST/OpenSoul"
  "$DEST/OpenSoul/install-desktop-entry.sh" >/dev/null || true
  mkdir -p "$HOME/.local/bin" && ln -sf "$DEST/OpenSoul/OpenSoul" "$HOME/.local/bin/opensoul-app"
  say "Installed $DEST/OpenSoul (menu entry added; command: opensoul-app)"
  [ "${OPENSOUL_NO_OPEN:-}" = 1 ] || "$DEST/OpenSoul/OpenSoul"
fi
