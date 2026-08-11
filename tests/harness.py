"""An isolated environment for the tests.

ccdo builds every path from XDG_DATA_HOME / XDG_CONFIG_HOME, so pointing those
at a temporary directory BEFORE the import is enough: the tests never touch
the real queue, registry or config.
"""
import atexit
import importlib.util
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "ccdo.py")

TMPDIR = tempfile.mkdtemp(prefix="ccdo-test-")
os.environ["XDG_DATA_HOME"] = os.path.join(TMPDIR, "data")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMPDIR, "config")

_spec = importlib.util.spec_from_file_location("ccdo_under_test", SRC)
jd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jd)

# Safety catch: do the paths really point into the temp directory? If not,
# the tests could damage the user's queue — so we stop right here.
if not jd.DATA_DIR.startswith(TMPDIR):
    sys.exit("SAFETY: DATA_DIR is not in the temp directory (%s) — stopped"
             % jd.DATA_DIR)

os.makedirs(jd.DATA_DIR, exist_ok=True)
os.makedirs(jd.DROPS_DIR, exist_ok=True)
os.makedirs(jd.CONFIG_DIR, exist_ok=True)

atexit.register(lambda: shutil.rmtree(TMPDIR, ignore_errors=True))

CFG = dict(jd.DEFAULT_CONFIG)
CFG["notify"] = False           # no desktop notifications during a test run
CFG["enter_delay"] = 0.0


# ---------------------------------------------------------------- transcript

def _a_text(t):
    return {"type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": t}]}}


def _a_tool():
    return {"type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "tool_use", "name": "Bash",
                                     "input": {"command": "ls"}}]}}


def _u_text(t):
    return {"type": "user", "message": {"role": "user", "content": t}}


def _u_result():
    return {"type": "user",
            "message": {"role": "user",
                        "content": [{"type": "tool_result", "content": "ok"}]}}


def transcript_lines(final_text=None):
    """A realistic Claude Code transcript.

    The previous turn's text (not a question), tool calls and tool_results,
    then optionally the text closing this turn. Leaving final_text=None stands
    for the moment the Stop hook runs before the last message hits disk.
    """
    rows = [_u_text("the previous request"),
            _a_text("The previous turn's text, not a question:"),
            _a_tool(), _u_result(), _a_tool(), _u_result()]
    if final_text is not None:
        rows.append(_a_text(final_text))
    return [json.dumps(r, ensure_ascii=False).encode("utf-8") + b"\n"
            for r in rows]


def write_transcript(path, lines):
    with open(path, "wb") as f:
        f.writelines(lines)
    return path


def tmp_path(name):
    return os.path.join(TMPDIR, name)


# -------------------------------------------------------------------- sonuc

class Results:
    """A tiny result collector — no pytest, so the project stays dependency-free."""

    def __init__(self, title):
        self.title = title
        self.rows = []
        print("== %s" % title)

    def check(self, ok, label, detail=""):
        self.rows.append(bool(ok))
        print("  %-4s %-46s %s" % ("OK" if ok else "FAIL", label, detail))
        return ok

    def finish(self):
        good = sum(self.rows)
        print("  -> %d/%d\n" % (good, len(self.rows)))
        return 0 if good == len(self.rows) else 1
