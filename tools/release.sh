#!/usr/bin/env bash
# Cut a release: bump the version, refresh what is generated, tag it.
#
#     tools/release.sh patch|minor|major|<version>
#
# Four things used to be done by hand and any one of them could be forgotten.
# The one that hurts is VERSION drifting from the tag: the update check reads
# the tag, so ccdo would keep offering an update the user already installed.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ $# -eq 1 ] || { echo "usage: tools/release.sh patch|minor|major|<version>"; exit 2; }

[ -z "$(git status --porcelain)" ] || {
  echo "!! the working tree is dirty — commit or stash first"; exit 1; }

current=$(python3 - <<'PY'
import re
print(re.search(r'^VERSION = "(.+)"', open("ccdo.py").read(), re.M).group(1))
PY
)

case "$1" in
  patch|minor|major)
    new=$(python3 - "$current" "$1" <<'PY'
import sys
major, minor, patch = (int(x) for x in sys.argv[1].split("."))
step = sys.argv[2]
if step == "major":
    major, minor, patch = major + 1, 0, 0
elif step == "minor":
    minor, patch = minor + 1, 0
else:
    patch += 1
print("%d.%d.%d" % (major, minor, patch))
PY
) ;;
  *) new="$1" ;;
esac

echo "$new" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || {
  echo "!! '$new' is not a MAJOR.MINOR.PATCH version"; exit 1; }

git rev-parse -q --verify "refs/tags/v$new" >/dev/null && {
  echo "!! tag v$new already exists"; exit 1; }

echo "==> $current -> $new"

python3 - "$new" <<'PY'
import re, sys
new = sys.argv[1]
src = open("ccdo.py", encoding="utf-8").read()
src = re.sub(r'^VERSION = ".+"', 'VERSION = "%s"' % new, src, count=1, flags=re.M)
open("ccdo.py", "w", encoding="utf-8").write(src)
PY

echo "==> Tests"
bash tests/run.sh >/dev/null || { echo "!! tests failed"; exit 1; }

echo "==> Rebuilding ccdo-setup.sh"
bash tools/make-setup.sh >/dev/null

echo "==> CHANGELOG.md"
python3 - "$new" <<'PY'
import datetime, os, subprocess, sys
new = sys.argv[1]
body = subprocess.run([sys.executable, "tools/changelog.py"],
                      capture_output=True, text=True).stdout.strip()
today = subprocess.run(["git", "log", "-1", "--format=%cs"],
                       capture_output=True, text=True).stdout.strip()
head = "## [%s] - %s\n\n%s\n" % (new, today, body)

path = "CHANGELOG.md"
old = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
marker = "<!-- releases -->"
if marker in old:
    before, after = old.split(marker, 1)
    out = before + marker + "\n\n" + head + after.lstrip("\n")
else:
    out = head + "\n" + old
open(path, "w", encoding="utf-8").write(out)
print(head)
PY

git add -A
git commit -q -m "chore(release): v$new"
git tag -a "v$new" -m "v$new"

cat <<EOF

Tagged v$new. Push it and the release workflow does the rest:

    git push origin main
    git push origin v$new
EOF
