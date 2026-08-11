#!/usr/bin/env bash
# ccdo uninstaller. It leaves your data alone — the queue, history, settings
# and images stay where they are; pass --purge to remove those too.
set -euo pipefail

PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
UNITS="$HOME/.config/systemd/user"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/ccdo"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/ccdo"

echo "==> Service"
systemctl --user disable --now ccdo.service 2>/dev/null || true
rm -f "$UNITS/ccdo.service"
systemctl --user daemon-reload 2>/dev/null || true

echo "==> Files"
rm -f "$BIN/ccdo" "$BIN/claude-tmux" "$BIN/ccdo-uninstall" "$APPS/ccdo.desktop"

echo "==> Claude Code hooks"
echo "   Remove the ccdo hooks from ~/.claude/settings.json by hand."
echo "   (install-hooks left a backup: settings.json.bak-*)"

if [ "$PURGE" = "1" ]; then
  echo "==> Removing data"
  rm -rf "$DATA" "$CONF"
else
  echo
  echo "Your data is still here:"
  echo "   $DATA"
  echo "   $CONF"
  echo "To remove that too: ccdo-uninstall --purge"
fi

echo
echo "Removed."
