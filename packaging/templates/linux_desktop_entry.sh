#!/usr/bin/env bash
# Adds OpenSoul to your applications menu (current user only, ~/.local/share/applications). Run once.
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$DEST"
cat > "$DEST/opensoul.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=OpenSoul
Comment=Make short films starring your own characters, on your own computer
Exec="$HERE/OpenSoul"
Icon=$HERE/OpenSoul.png
Terminal=false
Categories=AudioVideo;Graphics;
DESKTOP
echo "Added OpenSoul to your applications menu ($DEST/opensoul.desktop)."
