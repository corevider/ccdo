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

# Sahte tmux: has-session'a hangi adin soruldugunu ve new-session'in hangi
# adla cagrildigini yazar. cc-<dizin> zaten varsa -2 ekleniyor mu?
with open(os.path.join(stub, "tmux"), "w") as f:
    f.write("""#!/usr/bin/env bash
if [ "$1" = "has-session" ]; then
    # cagri: tmux has-session -t "=<ad>"  -> ad $3'te
    [ "$3" = "=cc-proje" ] && exit 0
    exit 1
fi
if [ "$1" = "new-session" ]; then
    echo "NEW-SESSION name=$3 cmd=$4"
    exit 0
fi
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
r.check("name=cc-proje-2" in out, "with a session of that name already up, a new one is opened", out)
r.check("--model opus" in out, "arguments are passed through", out)

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
