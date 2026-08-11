#!/usr/bin/env bash
# Builds ccdo-setup.sh from the CURRENT files in the repo.
#
# The package is a single self-extracting installer with the files embedded as
# base64. Never edit it by hand: the embedded payload goes stale as soon as the
# sources move. Run this whenever a source file changes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/ccdo-setup.sh"
FILES=(ccdo.py ccdo.desktop ccdo.service ccdo.plist install.sh uninstall.sh
       README.md LICENSE
       claude-commands/next.md claude-commands/queue.md
       locales/tr.json)

{
cat <<'HEADER'
#!/usr/bin/env bash
# ccdo — a self-extracting installer
# GENERATED FILE — do not edit; regenerate with tools/make-setup.sh.
set -euo pipefail

if [ "${CCDO_RELAUNCH:-}" != "1" ]; then
  _self="$(readlink -f "${BASH_SOURCE[0]}")"
  _tmp="$(mktemp /tmp/ccdo-setup.XXXXXX.sh)"
  cp "$_self" "$_tmp"
  trap 'rm -f "$_tmp"' EXIT
  CCDO_RELAUNCH=1 bash "$_tmp"
  exit $?
fi

DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
[ -z "${DESKTOP:-}" ] && DESKTOP="$HOME"
TARGET="$DESKTOP/ccdo"

if [ -e "$TARGET" ]; then
  echo "!! $TARGET already exists. Files inside it will be overwritten."
  read -rp "   Continue? [y/N] " ans
  case "$ans" in y|Y) ;; *) echo "Cancelled."; exit 1 ;; esac
fi
mkdir -p "$TARGET/claude-commands" "$TARGET/locales"

write_file() {
  local rel="$1" mode="$2" out="$TARGET/$1"
  mkdir -p "$(dirname "$out")"
  base64 -d > "$out"
  chmod "$mode" "$out"
  printf '   + %s\n' "$rel"
}

echo "==> Extracting to: $TARGET"
HEADER

for rel in "${FILES[@]}"; do
    case "$rel" in
        *.py|*.sh) mode=755 ;;
        *)         mode=644 ;;
    esac
    printf '\nwrite_file "%s" %s <<'"'"'__B64__'"'"'\n' "$rel" "$mode"
    base64 "$ROOT/$rel"
    printf '__B64__\n'
done

cat <<'FOOTER'

cat <<'EOF'

Extracted. To install:
    cd "$TARGET" && ./install.sh

Then install the Claude Code hooks:
    ccdo install-hooks
EOF
FOOTER
} > "$OUT"

chmod 755 "$OUT"
echo "built: $OUT ($(wc -c < "$OUT") bytes, ${#FILES[@]} files)"
