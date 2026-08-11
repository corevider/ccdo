#!/usr/bin/env python3
"""The settings file must open in a text editor, not a browser.

The menu used xdg-open, which goes by the extension — and .json is bound to
the browser on most desktops, so config.json opened in Firefox instead of an
editor. The order is now: the default application for text/plain -> the
editors we know of -> xdg-open as a last resort.
"""
from harness import jd, Results

r = Results("open a file in an editor")

PATH = "/tmp/ornek/config.json"


class Fake:
    """A fake environment recording everywhere open_in_editor reaches out."""

    def __init__(self, have=(), mime="org.gnome.TextEditor.desktop", launch_rc=0):
        self.have = set(have)
        self.mime = mime
        self.launch_rc = launch_rc
        self.calls = []

    def which(self, exe):
        return "/usr/bin/" + exe if exe in self.have else None

    def run_cmd(self, args, timeout=10):
        self.calls.append(args[0])
        if args[:3] == ["xdg-mime", "query", "default"]:
            return (0 if self.mime else 1), self.mime, ""
        if args[0] == "gtk-launch":
            return self.launch_rc, "", ""
        return 0, "", ""

    def popen(self, args, **kw):
        self.calls.append(args[0])
        return None


def run(fake):
    old = (jd.shutil.which, jd.run_cmd, jd.subprocess.Popen)
    jd.shutil.which, jd.run_cmd, jd.subprocess.Popen = (
        fake.which, fake.run_cmd, fake.popen)
    try:
        return jd.open_in_editor(PATH)
    finally:
        jd.shutil.which, jd.run_cmd, jd.subprocess.Popen = old


f = Fake(have=("gtk-launch", "gedit"))
ok = run(f)
r.check(ok and f.calls == ["xdg-mime", "gtk-launch"],
        "the default application for text/plain comes first", str(f.calls))
r.check("xdg-open" not in f.calls, "xdg-open, which would land in a browser, is not tried")

f = Fake(have=("gtk-launch", "gedit"), launch_rc=1)
ok = run(f)
r.check(ok and f.calls[-1] == "gedit",
        "if gtk-launch fails we fall back to a known editor", str(f.calls))

f = Fake(have=("gtk-launch",), mime="", launch_rc=1)
ok = run(f)
r.check(ok and f.calls[-1] == "xdg-open",
        "with none of them, xdg-open is the last resort", str(f.calls))

f = Fake(have=("kate",))
ok = run(f)
r.check(ok and f.calls == ["kate"],
        "without gtk-launch the mime query is not even made", str(f.calls))

f = Fake(have=("gtk-launch", "code", "gedit"), launch_rc=1)
run(f)
r.check(f.calls[-1] == "gedit",
        "the editor order is fixed: gedit is tried before code", str(f.calls))

raise SystemExit(r.finish())
