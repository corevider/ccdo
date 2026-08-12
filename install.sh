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
  # Install the latest release by default. main is where work in progress
  # lands, so handing it to someone running the install line would give them
  # something that was never released. CCDO_REF overrides it — `ccdo update`
  # passes the tag it just told you about, and you can name any tag or branch.
  REF="${CCDO_REF:-}"
  if [ -z "$REF" ]; then
    REF="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
           | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1)"
    # No releases yet, or the API is unreachable: main is the only thing left.
    [ -n "$REF" ] || REF=main
  fi
  case "$REF" in
    v*) url="https://github.com/$REPO/archive/refs/tags/$REF.tar.gz" ;;
    *)  url="https://github.com/$REPO/archive/refs/heads/$REF.tar.gz" ;;
  esac
  echo "   version: $REF"
  curl -fsSL "$url" | tar xz -C "$SRC" --strip-components=1
fi
case "$(uname -s)" in
  Darwin) OS=mac ;;
  Linux)  OS=linux ;;
  *)      OS=other ;;
esac

BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
UNITS="$HOME/.config/systemd/user"
LOCALES="${XDG_DATA_HOME:-$HOME/.local/share}/ccdo/locales"
AGENTS="$HOME/Library/LaunchAgents"

echo "==> Dependencies"
# Only reach for a package manager if something is actually missing. An update
# run has everything already, and asking for sudo then would stall a
# GUI-triggered update where there is no terminal to type a password into.
missing=0
if [ "$OS" = "mac" ]; then
  python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk" \
    >/dev/null 2>&1 || missing=1
  # Every symbolic icon in the window is an SVG, and GdkPixbuf reads SVG only
  # with librsvg. Without it the toolbar comes up full of broken-image
  # placeholders, so it counts as a missing dependency, not a nicety.
  python3 -c "import gi; gi.require_version('GdkPixbuf','2.0')
from gi.repository import GdkPixbuf
raise SystemExit(0 if any(f.get_name() == 'svg' for f in GdkPixbuf.Pixbuf.get_formats()) else 1)" \
    >/dev/null 2>&1 || missing=1
  command -v tmux >/dev/null 2>&1 || missing=1
  # The menu bar app is native, and PyObjC is the bridge to it.
  python3 -c "import AppKit" >/dev/null 2>&1 || missing=1
else
  python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk" \
    >/dev/null 2>&1 || missing=1
  python3 -c "import gi; gi.require_version('AyatanaAppIndicator3','0.1')" \
    >/dev/null 2>&1 || python3 -c "import gi; gi.require_version('AppIndicator3','0.1')" \
    >/dev/null 2>&1 || missing=1
  for cmd in tmux notify-send; do
    command -v "$cmd" >/dev/null 2>&1 || missing=1
  done
fi

if [ "${CCDO_SKIP_DEPS:-}" = "1" ] || [ "$missing" = "0" ]; then
  echo "   already satisfied, skipping the package manager"
elif [ "$OS" = "mac" ]; then
  if command -v brew >/dev/null 2>&1; then
    brew install pygobject3 gtk+3 librsvg adwaita-icon-theme tmux
    # PyObjC has no formula; Homebrew's Python is externally managed, so pip
    # needs telling that installing into it is deliberate.
    python3 -m pip install --quiet pyobjc-framework-Cocoa 2>/dev/null \
      || python3 -m pip install --quiet --break-system-packages \
           pyobjc-framework-Cocoa 2>/dev/null \
      || echo "!! could not install PyObjC — the menu bar app will not start"
  else
    echo "!! Homebrew not found — install it first: https://brew.sh"
    echo "   then: brew install pygobject3 gtk+3 librsvg adwaita-icon-theme tmux"
  fi
elif command -v apt >/dev/null 2>&1; then
  sudo apt update
  sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
       gir1.2-ayatanaappindicator3-0.1 libnotify-bin tmux xdotool xclip wl-clipboard
elif command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y python3-gobject gtk3 libappindicator-gtk3 \
       libnotify tmux xdotool xclip wl-clipboard
elif command -v pacman >/dev/null 2>&1; then
  sudo pacman -S --needed --noconfirm python-gobject gtk3 \
       libayatana-appindicator libnotify tmux xdotool xclip wl-clipboard
elif command -v zypper >/dev/null 2>&1; then
  sudo zypper install -y python3-gobject python3-gobject-Gdk \
       libayatana-appindicator3-1 libnotify-tools tmux xdotool xclip wl-clipboard
else
  echo "!! Unknown package manager. Install these by hand:"
  echo "   python3-gobject (PyGObject), GTK 3, an AppIndicator library,"
  echo "   libnotify, tmux"
fi

# On GNOME the tray icon needs this extension:
if [ "$OS" = "linux" ] && { [ "${XDG_CURRENT_DESKTOP:-}" = "GNOME" ] || [ "${XDG_CURRENT_DESKTOP:-}" = "ubuntu:GNOME" ]; }; then
  if ! gnome-extensions list 2>/dev/null | grep -qi appindicator; then
    echo "!! On GNOME the tray icon needs the AppIndicator extension:"
    echo "   sudo apt install -y gnome-shell-extension-appindicator"
    echo "   gnome-extensions enable ubuntu-appindicators@ubuntu.com"
  fi
fi

echo "==> Files"
mkdir -p "$BIN" "$APPS" "$UNITS"
# Pick an interpreter that can actually import the GUI bridge. `env python3`
# is not enough: on macOS Homebrew installs into its own Python while
# /usr/bin/python3 wins the PATH, and a virtualenv can do the same on Linux.
# The queue and the hooks run on any python3, but the interface needs this one.
if [ "$OS" = "mac" ]; then
  # One interpreter with both is best: PyObjC drives the menu bar, gi still
  # draws `ccdo show`. Apple's /usr/bin/python3 carries PyObjC but no gi, so
  # accept PyObjC alone rather than fall back to a Python with neither.
  BEST="import AppKit, gi"; NEED="import AppKit"
  NEED_NAME="PyObjC"; NEED_UI="menu bar app"
else
  BEST="import gi"; NEED="import gi"
  NEED_NAME="PyGObject"; NEED_UI="tray window"
fi
PY=""
for probe in "$BEST" "$NEED"; do
  for cand in "$(command -v python3 || true)" /opt/homebrew/bin/python3 \
              /usr/local/bin/python3 /usr/bin/python3; do
    [ -x "$cand" ] || continue
    if "$cand" -c "$probe" >/dev/null 2>&1; then PY="$cand"; break; fi
  done
  [ -n "$PY" ] && break
done
if [ -z "$PY" ]; then
  PY="$(command -v python3)"
  echo "   no python3 with $NEED_NAME found — installing for $PY"
  echo "   (the queue and the hooks work; the $NEED_UI will not start)"
else
  echo "   interpreter: $PY"
fi

install -m 755 "$SRC/ccdo.py" "$BIN/ccdo"
# Rewrite the shebang so ccdo always runs under the interpreter we picked.
tmp_ccdo="$(mktemp)"
{ printf '#!%s\n' "$PY"; tail -n +2 "$BIN/ccdo"; } > "$tmp_ccdo"
install -m 755 "$tmp_ccdo" "$BIN/ccdo"
rm -f "$tmp_ccdo"
install -m 755 "$SRC/tools/claude-tmux" "$BIN/claude-tmux"
install -m 755 "$SRC/uninstall.sh" "$BIN/ccdo-uninstall"
if [ -d "$SRC/locales" ]; then
  install -d "$LOCALES"
  install -m 644 "$SRC/locales/"*.json "$LOCALES/"
fi
if [ "$OS" = "linux" ]; then
  sed "s|@BIN@|$BIN|" "$SRC/ccdo.desktop" > "$APPS/ccdo.desktop"
  install -m 644 "$SRC/ccdo.service" "$UNITS/ccdo.service"
elif [ "$OS" = "mac" ]; then
  install -d "$AGENTS"
  sed "s|@BIN@|$BIN|" "$SRC/ccdo.plist" > "$AGENTS/com.corevider.ccdo.plist"
fi

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "!! $BIN is not on PATH. Add this to ~/.bashrc or ~/.zshrc:"
     echo "   export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

echo "==> Service"
if [ "$OS" = "linux" ] && command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload
  systemctl --user enable --now ccdo.service || {
    echo "systemd failed — you can run the 'ccdo' command by hand."
  }
elif [ "$OS" = "mac" ]; then
  # launchd is the equivalent of the systemd user unit: start at login and
  # come back after a crash.
  plist="$AGENTS/com.corevider.ccdo.plist"
  launchctl bootout "gui/$(id -u)/com.corevider.ccdo" 2>/dev/null || true
  if launchctl bootstrap "gui/$(id -u)" "$plist" 2>/dev/null; then
    echo "   launchd agent loaded (starts at login)"
  else
    launchctl load -w "$plist" 2>/dev/null \
      && echo "   launchd agent loaded (starts at login)" \
      || echo "   could not load the launchd agent — run 'ccdo' by hand"
  fi
else
  echo "   no service manager here — run 'ccdo' by hand."
fi

# The hooks are what make the session match exact instead of guessed, and
# everybody who installs ccdo wants them — leaving it as a step to remember
# only meant it got forgotten. It merges into ~/.claude/settings.json rather
# than overwriting, takes a backup first, and re-running replaces its own
# entries instead of piling up. CCDO_SKIP_HOOKS=1 opts out.
echo "==> Claude Code hooks"
if [ "${CCDO_SKIP_HOOKS:-}" = "1" ]; then
  echo "   skipped (CCDO_SKIP_HOOKS=1) — run 'ccdo install-hooks' when you want them"
else
  "$BIN/ccdo" install-hooks || echo "!! could not install the hooks — run 'ccdo install-hooks'"
fi

cat <<'EOF'

Installed. Restart any running Claude Code sessions so they pick up the hooks.

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
