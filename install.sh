#!/usr/bin/env bash
# Install hypr-displays for the current user.
#
#   ./install.sh            copy the app to ~/.local/bin
#   ./install.sh --link     symlink instead (handy while developing)
#   ./install.sh --uninstall
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_DIR/applications"
LIB_DIR="$DATA_DIR/hypr-displays"

case "${1:-}" in
  --uninstall)
    rm -f "$BIN_DIR/hypr-displays" "$APP_DIR/hypr-displays.desktop"
    rm -rf "$LIB_DIR"
    echo "Removed hypr-displays. Your monitors.lua was left untouched."
    exit 0
    ;;
  --link) mode=link ;;
  "") mode=copy ;;
  *) echo "usage: $0 [--link|--uninstall]" >&2; exit 1 ;;
esac

python3 -c 'import gi; gi.require_version("Gtk", "4.0")' 2>/dev/null || {
  echo "Missing dependency: GTK 4 for Python. On Arch: sudo pacman -S python-gobject gtk4" >&2
  exit 1
}

mkdir -p "$BIN_DIR" "$APP_DIR"
if [[ $mode == link ]]; then
  ln -sf "$SRC/hypr-displays" "$BIN_DIR/hypr-displays"
else
  # The app imports hypr_displays_core.py from its own (real) directory.
  install -Dm 755 "$SRC/hypr-displays" "$LIB_DIR/hypr-displays"
  install -Dm 644 "$SRC/hypr_displays_core.py" "$LIB_DIR/hypr_displays_core.py"
  ln -sf "$LIB_DIR/hypr-displays" "$BIN_DIR/hypr-displays"
fi
install -m 644 "$SRC/hypr-displays.desktop" "$APP_DIR/hypr-displays.desktop"

echo "Installed hypr-displays to $BIN_DIR ($mode)."
echo "Launch it from your app launcher (\"Displays\") or run: hypr-displays"
