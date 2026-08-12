#!/usr/bin/env python3
"""A session started inside tmux must get a permanent pane target.

That is the only way to hand a task to a session sitting idle: outside tmux we
cannot type into the terminal (on Wayland every route for injecting keys is
closed), so delivery waits for the Stop hook. Inside tmux the target is a pane
ID and send-keys works in every case.
"""
import os
import subprocess
import sys

from harness import jd, Results, CFG

r = Results("tmux pane target")
store = jd.Store(CFG)
reg = jd.Registry()

SID = "pane-target-test"
PANE = "%42"


def start_session(env_pane):
    """Run the SessionStart hook with a given TMUX_PANE."""
    old = os.environ.get("TMUX_PANE")
    if env_pane is None:
        os.environ.pop("TMUX_PANE", None)
    else:
        os.environ["TMUX_PANE"] = env_pane
    try:
        jd.hook_session_start(CFG, store, reg, {
            "session_id": SID, "cwd": "/home/you/dev/ccdo",
            "transcript_path": "/tmp/yok.jsonl"})
    finally:
        if old is None:
            os.environ.pop("TMUX_PANE", None)
        else:
            os.environ["TMUX_PANE"] = old
    return (reg.get(SID) or {}).get("target")


# --- tmux icinde ----------------------------------------------------------
target = start_session(PANE)
r.check(target == PANE, "inside tmux the target is a pane ID", target)
r.check(jd.is_tmux_target(target) is True, "a pane target counts as a tmux target")

# --- tmux disinda ---------------------------------------------------------
target = start_session(None)
r.check(target == jd.SID_PREFIX + SID, "outside tmux, a virtual sid: target", target)
r.check(jd.is_tmux_target(target) is False, "a sid: target is not a tmux target")

# --- the wrapper: session naming and not nesting -------------------------
WRAP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "claude-tmux")
r.check(os.access(WRAP, os.X_OK), "claude-tmux is executable")

stub = os.path.join(jd.TMPDIR if hasattr(jd, "TMPDIR") else "/tmp", "stub")
os.makedirs(stub, exist_ok=True)

# A fake tmux that reports the calls the wrapper makes. cc-<dir> already
# exists, so the wrapper has to pick cc-<dir>-2; and the pane has to be split
# off after the options are set, or it keeps the default history.
with open(os.path.join(stub, "tmux"), "w") as f:
    f.write("""#!/usr/bin/env bash
case "$1" in
  has-session)
    # called as: tmux has-session -t "=<name>"
    [ "$3" = "=cc-proje" ] && exit 0
    exit 1 ;;
  new-session)   echo "NEW-SESSION args=$*" ;;
  set-option)    echo "SET $4=$5" ;;
  split-window)  echo "SPLIT target=$4 cmd=$5" ;;
  kill-pane)     echo "KILL $3" ;;
  attach-session) echo "ATTACH $3" ;;
esac
exit 0
""")
os.chmod(os.path.join(stub, "tmux"), 0o755)

with open(os.path.join(stub, "claude"), "w") as f:
    f.write("#!/usr/bin/env bash\necho STUB-CLAUDE \"$@\"\n")
os.chmod(os.path.join(stub, "claude"), 0o755)

proje = os.path.join(stub, "proje")
os.makedirs(proje, exist_ok=True)

env = dict(os.environ, PATH=stub + os.pathsep + os.environ["PATH"])
env.pop("TMUX", None)
out = subprocess.run([WRAP, "--model", "opus"], cwd=proje, env=env,
                     capture_output=True, text=True).stdout.strip()
r.check("cc-proje-2" in out, "with a session of that name already up, a new one is opened", out)
r.check("--model opus" in out, "arguments are passed through", out)

# The options have to be set before the pane exists: tmux applies
# history-limit at pane creation, and setting it afterwards leaves the running
# pane on the old value.
lines = out.splitlines()
def first(prefix):
    return next((i for i, l in enumerate(lines) if l.startswith(prefix)), -1)

r.check(first("SET history-limit") >= 0 and first("SPLIT") >= 0
        and first("SET history-limit") < first("SPLIT"),
        "history-limit is set before the pane is created", out)
r.check(any(l.startswith("SET mouse=on") for l in lines),
        "the mouse is turned on, so the wheel scrolls the pane", out)
r.check(first("SPLIT") < first("KILL"),
        "the throwaway shell is killed only after the real pane exists", out)

# Opting out has to be honoured, since it changes how selection behaves.
out_nomouse = subprocess.run([WRAP], cwd=proje, env=dict(env, CCDO_TMUX_MOUSE="0"),
                             capture_output=True, text=True).stdout
r.check("SET mouse=on" not in out_nomouse,
        "CCDO_TMUX_MOUSE=0 leaves the mouse alone", out_nomouse.strip())

# tmux icindeyken ic ice sokmamali: dogrudan claude calismali
env2 = dict(env, TMUX="/tmp/tmux-1000/default,123,0")
out2 = subprocess.run([WRAP], cwd=proje, env=env2,
                      capture_output=True, text=True).stdout.strip()
r.check(out2.startswith("STUB-CLAUDE"), "already inside tmux, it does not nest", out2)

# Non-interactive calls must not open tmux
for args, label in ((["-p", "merhaba"], "-p (print)"),
                    (["--version"], "--version"),
                    (["mcp", "list"], "mcp alt komutu")):
    out3 = subprocess.run([WRAP] + args, cwd=proje, env=env,
                          capture_output=True, text=True).stdout.strip()
    r.check(out3.startswith("STUB-CLAUDE"), "does not open tmux: %s" % label, out3)

sys.exit(r.finish())
