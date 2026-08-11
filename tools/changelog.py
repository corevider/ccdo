#!/usr/bin/env python3
"""Build release notes from conventional commits.

    tools/changelog.py [<from>] [<to>]

With no arguments it takes everything since the previous tag. The output is
markdown, grouped by type; anything that carries no user-visible change
(chore, docs, test, style, refactor) is left out — a release note is for the
person updating, not a mirror of the log.

Both the release workflow and tools/release.sh call this, so the notes in a
GitHub release and the section in CHANGELOG.md cannot say different things.
"""
import re
import subprocess
import sys

# Order matters: this is the order the sections appear in.
SECTIONS = [
    ("feat", "Added"),
    ("fix", "Fixed"),
    ("perf", "Performance"),
]
HIDDEN = ("chore", "docs", "test", "style", "refactor", "ci", "build")

HEADER = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?: (?P<subject>.+)$")


def run(*args):
    out = subprocess.run(["git", *args], capture_output=True, text=True)
    return out.stdout.strip()


def previous_tag(ref):
    """The tag before `ref`, or the empty string if this is the first one."""
    return run("describe", "--tags", "--abbrev=0", "%s^" % ref)


def commits(rev_range):
    raw = run("log", "--no-merges", "--format=%H%x1f%s%x1f%b%x1e", rev_range)
    for chunk in raw.split("\x1e"):
        chunk = chunk.strip("\n")
        if chunk:
            sha, subject, body = (chunk.split("\x1f") + ["", ""])[:3]
            yield sha, subject, body


def parse(subject, body):
    m = HEADER.match(subject)
    if not m:
        return None
    breaking = bool(m.group("bang")) or "BREAKING CHANGE" in body
    return {"type": m.group("type"), "scope": m.group("scope"),
            "subject": m.group("subject"), "breaking": breaking}


def notes(rev_range):
    groups, breaking, other = {}, [], []
    for sha, subject, body in commits(rev_range):
        item = parse(subject, body)
        if item is None:
            # A commit that does not follow the convention is still a change;
            # dropping it silently would hide work from the release notes.
            other.append((subject, sha))
            continue
        line = item["subject"]
        if item["scope"]:
            line = "**%s:** %s" % (item["scope"], line)
        if item["breaking"]:
            breaking.append((line, sha))
        elif item["type"] not in HIDDEN:
            groups.setdefault(item["type"], []).append((line, sha))

    out = []

    def block(title, rows):
        if not rows:
            return
        out.append("### %s" % title)
        out.append("")
        out.extend("- %s (%s)" % (line, sha[:7]) for line, sha in rows)
        out.append("")

    block("Breaking changes", breaking)
    for kind, title in SECTIONS:
        block(title, groups.get(kind, []))
    block("Other", other)
    return "\n".join(out).strip()


def main(argv):
    to = argv[2] if len(argv) > 2 else "HEAD"
    if len(argv) > 1:
        frm = argv[1]
    else:
        frm = previous_tag(to)
    rev_range = "%s..%s" % (frm, to) if frm else to
    text = notes(rev_range)
    print(text if text else "_No user-visible changes._")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
