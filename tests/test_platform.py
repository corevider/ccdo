#!/usr/bin/env python3
"""The desktop calls have to bend to the platform, not assume Linux.

The queue, the hooks and the tmux delivery run on any Unix; only a handful of
places shell out to a desktop tool. Each of those has to pick the right one —
and, where the platform offers nothing, do nothing rather than fail.

These run on Linux, so the macOS branches are exercised by flipping the flag
the code itself reads.
"""
from harness import jd, Results

r = Results("platform")


class Calls:
    """Record what would have been run instead of running it."""

    def __init__(self, have=(), rc=0, out=""):
        self.have, self.rc, self.out = set(have), rc, out
        self.ran = []

    def which(self, exe):
        return "/usr/bin/" + exe if exe in self.have else None

    def run_cmd(self, args, timeout=10):
        self.ran.append(list(args))
        return self.rc, self.out, ""

    def run(self, args, **kw):
        self.ran.append(list(args))
        return None

    def popen(self, args, **kw):
        self.ran.append(list(args))
        return None


def on_platform(mac, calls, fn):
    """Run fn as though we were on macOS (or not), with the world faked out."""
    saved = (jd.IS_MAC, jd.shutil.which, jd.run_cmd,
             jd.subprocess.run, jd.subprocess.Popen)
    jd.IS_MAC = mac
    jd.shutil.which, jd.run_cmd = calls.which, calls.run_cmd
    jd.subprocess.run, jd.subprocess.Popen = calls.run, calls.popen
    try:
        return fn()
    finally:
        (jd.IS_MAC, jd.shutil.which, jd.run_cmd,
         jd.subprocess.run, jd.subprocess.Popen) = saved


# ------------------------------------------------------------ notifications

c = Calls(have=("notify-send",))
on_platform(False, c, lambda: jd.notify("t", "b", {"notify": True}))
r.check(c.ran and c.ran[0][0] == "notify-send", "Linux notifies with notify-send",
        str(c.ran))

c = Calls(have=("osascript",))
on_platform(True, c, lambda: jd.notify("t", "b", {"notify": True}))
r.check(c.ran and c.ran[0][0] == "osascript", "macOS notifies with osascript",
        str(c.ran))

c = Calls(have=())
on_platform(True, c, lambda: jd.notify("t", "b", {"notify": True}))
r.check(not c.ran, "with no notifier present, nothing is run")

c = Calls(have=("osascript",))
on_platform(True, c, lambda: jd.notify("t", "b", {"notify": False}))
r.check(not c.ran, "the notify setting is honoured on every platform")

# A note with a quote in it would end the AppleScript string early.
q = jd.applescript_string('say "hi" \\ ok')
r.check(q == '"say \\"hi\\" \\\\ ok"', "quotes and backslashes are escaped", q)
r.check(jd.applescript_string(None) == '""', "no text is still a valid string")


# ------------------------------------------------------------------- theme

c = Calls(rc=0, out="Dark\n")
r.check(on_platform(True, c, jd.prefers_dark) is True,
        "macOS reports dark from AppleInterfaceStyle")
r.check(c.ran and c.ran[0][:3] == ["defaults", "read", "-g"],
        "macOS is not asked through gsettings", str(c.ran))

# The key exists only while dark is on; a non-zero exit means light.
c = Calls(rc=1, out="")
r.check(on_platform(True, c, jd.prefers_dark) is False,
        "macOS with the key absent means light")


# ------------------------------------------------------------------ editor

c = Calls(have=("gtk-launch",))
on_platform(True, c, lambda: jd.open_in_editor("/tmp/x.json"))
r.check(c.ran and c.ran[0][:2] == ["open", "-t"],
        "macOS opens the file in a text editor, not by extension", str(c.ran))

c = Calls(have=("gtk-launch", "gedit"))
on_platform(False, c, lambda: jd.open_in_editor("/tmp/x.json"))
r.check(c.ran and c.ran[0][0] == "xdg-mime",
        "Linux still resolves through text/plain first", str(c.ran))


# -------------------------------------------------------------- the window

r.check(jd.IS_MAC is False and jd.IS_WINDOWS is False,
        "the flags describe the machine running the tests")

raise SystemExit(r.finish())
