#!/usr/bin/env bash
# ccdo installer — Debian/Ubuntu
set -euo pipefail

REPO="corevider/ccdo"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"

# Run through `curl ... | bash` there are no files beside us: fetch the source.
if [ -z "$SRC" ] || [ ! -f "$SRC/ccdo.py" ]; then
  echo "==> Fetching the source ($REPO)"
  need() { command -v "$1" >/dev/null 2>&1 || { echo "!! $1 is required"; exit 1; }; }
  need curl; need tar
  SRC="$(mktemp -d)"
  trap 'rm -rf "$SRC"' EXIT
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" \
    | tar xz -C "$SRC" --strip-components=1
fi
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
UNITS="$HOME/.config/systemd/user"
LOCALES="${XDG_DATA_HOME:-$HOME/.local/share}/ccdo/locales"

echo "==> Dependencies"
if command -v apt >/dev/null 2>&1; then
  sudo apt update
  sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
       gir1.2-ayatanaappindicator3-0.1 libnotify-bin tmux xdotool xclip
else
  echo "No apt — install python3-gi, gtk3, ayatana-appindicator, libnotify and tmux by hand."
fi

# On GNOME the tray icon needs this extension:
if [ "${XDG_CURRENT_DESKTOP:-}" = "GNOME" ] || [ "${XDG_CURRENT_DESKTOP:-}" = "ubuntu:GNOME" ]; then
  if ! gnome-extensions list 2>/dev/null | grep -qi appindicator; then
    echo "!! On GNOME the tray icon needs the AppIndicator extension:"
    echo "   sudo apt install -y gnome-shell-extension-appindicator"
    echo "   gnome-extensions enable ubuntu-appindicators@ubuntu.com"
  fi
fi

echo "==> Files"
mkdir -p "$BIN" "$APPS" "$UNITS"
install -m 755 "$SRC/ccdo.py" "$BIN/ccdo"
install -m 755 "$SRC/tools/claude-tmux" "$BIN/claude-tmux"
install -m 755 "$SRC/uninstall.sh" "$BIN/ccdo-uninstall"
if [ -d "$SRC/locales" ]; then
  install -d "$LOCALES"
  install -m 644 "$SRC/locales/"*.json "$LOCALES/"
fi
sed "s|@BIN@|$BIN|" "$SRC/ccdo.desktop" > "$APPS/ccdo.desktop"
install -m 644 "$SRC/ccdo.service" "$UNITS/ccdo.service"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "!! $BIN is not on PATH. Add this to ~/.bashrc or ~/.zshrc:"
     echo "   export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

echo "==> Service"
systemctl --user daemon-reload
systemctl --user enable --now ccdo.service || {
  echo "systemd failed — you can run the 'ccdo' command by hand."
}

cat <<'EOF'

Installed.

IMPORTANT: install the Claude Code hooks too — they make the session match
exact instead of guessed:
    ccdo install-hooks
Then restart any running Claude Code sessions.

Next steps
----------
1) Bind a shortcut (GNOME -> Settings -> Keyboard -> Custom Shortcuts):
     Command: $HOME/.local/bin/ccdo show
     Key    : Super+N

2) Start Claude Code inside tmux, so even an idle session gets a task at once:
     echo 'alias claude=claude-tmux' >> ~/.bashrc

3) Try it:
     ccdo add "a test note"
     ccdo list

Version and updates
-------------------
     ccdo version --check      # is a newer one out
     ccdo update               # print the update command
To remove it: ccdo-uninstall

EOF
