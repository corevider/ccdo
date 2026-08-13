#!/usr/bin/env python3
"""The task text must land in Claude's prompt exactly as written.

Every multi-line note used to be written to a drop file, with only a "read
this file" line going to the session — costing Claude an extra read just to
see the task. The text now goes in one piece as a bracketed paste; files are
left for very long text only.
"""
import os
import shutil
import subprocess
import tempfile
import time

from harness import jd, Results, CFG

r = Results("task text delivery")
store = jd.Store(CFG)

PROBE = r'''
import os, sys, termios, tty
out = sys.argv[1]
fd = sys.stdin.fileno()
old = termios.tcgetattr(fd)
tty.setraw(fd)
sys.stdout.write("\x1b[?2004h")
sys.stdout.flush()
buf = b""
try:
    while True:
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        buf += chunk
        with open(out, "wb") as f:
            f.write(buf)
finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
'''

MULTI = "first line\nsecond line\nthird line"


def payload_for(text, cfg=None):
    task = store.add(text, target="%0")
    try:
        return jd.prepare_payload(cfg or CFG, task)
    finally:
        store.delete(task["id"])


# ----------------------------------------------------------------- text

payload, drop = payload_for(MULTI)
r.check(drop is None and payload == MULTI,
        "a multi-line note does not fall back to a file", repr(payload[:30]))

payload, drop = payload_for("one line")
r.check(drop is None and payload == "one line", "a single line goes directly")

payload, drop = payload_for("long " * 4000)
r.check(drop is not None and payload.endswith("and do the task in it."),
        "very long text does fall back to a file", os.path.basename(drop or ""))
r.check(bool(drop) and MULTI not in open(drop, encoding="utf-8").read()
        and "long long" in open(drop, encoding="utf-8").read(),
        "the drop file holds the task text")

payload, drop = payload_for(MULTI, dict(CFG, send_prefix="[ccdo] "))
r.check(payload == "[ccdo] " + MULTI, "send_prefix is applied to multi-line text too")


# ------------------------------------------------------------------ uri

with tempfile.TemporaryDirectory() as tmp:
    png = os.path.join(tmp, "screen shot.png")
    open(png, "wb").close()
    txt = os.path.join(tmp, "note.txt")
    open(txt, "wb").close()
    uris = ["file://" + png.replace(" ", "%20"),
            "file://" + txt,
            "file:///no/such/file.png",
            "https://example.com/a.png"]
    got = jd.file_paths_from_uris(uris)
    r.check(got == [png, txt],
            "every file is picked out of a URI list, image or not", str(got))
    r.check("/no/such/file.png" not in got and not any("example.com" in g
                                                      for g in got),
            "what does not exist as a file is left out", str(got))

r.check(jd.file_paths_from_uris(None) == [], "an empty URI list causes no trouble")


# ----------------------------------------------------------- screenshot file

# Command+Shift+4 writes a file and leaves the clipboard alone, so a paste
# right after taking a screenshot has to go and find it.
with tempfile.TemporaryDirectory() as tmp:
    now = 1_000_000.0

    def shot(name, age):
        path = os.path.join(tmp, name)
        open(path, "wb").close()
        os.utime(path, (now - age, now - age))
        return path

    old_shot = shot("old.png", 600)
    r.check(jd.recent_screenshot(120, tmp, now) is None,
            "a screenshot from ten minutes ago is not what you meant to paste")

    fresh = shot("fresh.png", 5)
    r.check(jd.recent_screenshot(120, tmp, now) == fresh,
            "one taken moments ago is")

    newer = shot("newer.png", 1)
    r.check(jd.recent_screenshot(120, tmp, now) == newer,
            "and the newest of several wins")

    shot(".hidden.png", 1)
    shot("notes.txt", 1)
    r.check(jd.recent_screenshot(120, tmp, now) == newer,
            "hidden files and non-images are not screenshots")

    r.check(jd.recent_screenshot(0, tmp, now) is None,
            "zero seconds turns the whole thing off")
    r.check(jd.recent_screenshot(120, os.path.join(tmp, "gone"), now) is None,
            "a folder that is not there is not an error")


# ----------------------------------------------------------- tmux delivery

def probe_bytes(payload):
    """Type a payload into a real tmux pane and return the raw bytes it saw."""
    tmp = tempfile.mkdtemp(prefix="ccdo-paste-")
    script = os.path.join(tmp, "probe.py")
    out = os.path.join(tmp, "got.bin")
    with open(script, "w", encoding="utf-8") as f:
        f.write(PROBE)
    sess = "ccdo-test-paste"
    subprocess.run(["tmux", "kill-session", "-t", sess],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["tmux", "new-session", "-d", "-s", sess, "-x", "100", "-y", "30",
                    "python3 %s %s" % (script, out)], check=True)
    try:
        time.sleep(0.5)
        ok, err = jd.tmux_type(sess, payload)
        time.sleep(0.4)
        data = open(out, "rb").read() if os.path.exists(out) else b""
        return ok, err, data
    finally:
        subprocess.run(["tmux", "kill-session", "-t", sess],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(tmp, ignore_errors=True)


if not shutil.which("tmux"):
    r.check(True, "no tmux — the pane test was skipped")
else:
    ok, err, data = probe_bytes(MULTI)
    r.check(ok, "tmux_type types multi-line text", err)
    r.check(data == b"\x1b[200~" + MULTI.encode() + b"\x1b[201~",
            "the text arrives inside a bracketed paste with raw newlines",
            repr(data[:24]))
    r.check(b"\r" not in data,
            "newlines are not turned into carriage returns (no early submit)")

    ok, err, data = probe_bytes("one line")
    r.check(ok and data == b"one line",
            "single-line text goes through send-keys unchanged", repr(data))

raise SystemExit(r.finish())
