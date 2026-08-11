#!/usr/bin/env python3
"""deliver(): no delivery route may stay open while Claude is asking.

There are two, and both would stand in for the user's answer:
  - send-keys into tmux (the send button / ccdo send)
  - for sessions outside tmux, queueing the task for the Stop hook
"""
import shutil
import subprocess
import sys
import time

from harness import jd, Results, CFG

store = jd.Store(CFG)
reg = jd.Registry()
r = Results("delivery lock")


SID = "sess-lock"      # one record, so by_target always finds the same one


def try_send(target, state, force=False, text="KILIT TESTI"):
    reg.upsert(SID, state=state, target=target, cwd="/tmp/x",
               auto_advance=True)
    task = store.add(text, target=target)
    ok, msg = jd.deliver(CFG, store, task, force=force)
    fresh = next((t for t in store.all() if t["id"] == task["id"]), {})
    store.delete(task["id"])
    return ok, msg, fresh


# ------------------------------------------------------- tmux disi (sid:)
# Burada "gonderildi" demek gorevi siraya almak: push=False isaretlenir ve
# sonraki Stop hook'unda Claude'a enjekte edilir. Yani kilit burada da sart.
TGT = "sid:test-nontmux"

ok, msg, _ = try_send(TGT, "asking")
r.check(ok is False, "outside tmux / asking", msg[:44])

ok, msg, task = try_send(TGT, "asking", force=True)
r.check(ok is True and task.get("push") is False, "outside tmux / asking + force",
        "siraya alindi")

ok, msg, _ = try_send(TGT, "waiting")
r.check(ok is False, "outside tmux / waiting (permission prompt)", msg[:44])

ok, msg, _ = try_send(TGT, "ended")
r.check(ok is False, "outside tmux / ended", msg[:44])

ok, msg, _ = try_send(TGT, "idle")
r.check(ok is True, "outside tmux / idle", "gecmeli")


# -------------------------------------------------------------------- tmux
if not shutil.which("tmux"):
    print("  ATLA tmux yok — send-keys yolu sinanmadi")
else:
    SESSION = "ccdo-selftest"
    subprocess.run(["tmux", "kill-session", "-t", SESSION],
                   capture_output=True)
    subprocess.run(["tmux", "new-session", "-d", "-s", SESSION,
                    "-x", "100", "-y", "20", "cat"], check=True)
    try:
        panes = subprocess.run(
            ["tmux", "list-panes", "-a", "-F",
             "#{session_name}:#{window_index}.#{pane_index}"],
            capture_output=True, text=True).stdout.split()
        pane = next(p for p in panes if p.startswith(SESSION + ":"))

        def pane_has(needle):
            time.sleep(0.6)
            out = subprocess.run(["tmux", "capture-pane", "-p", "-t", pane],
                                 capture_output=True, text=True).stdout
            return needle in out

        ok, msg, _ = try_send(pane, "asking", text="ASKING GECMEMELI")
        r.check(ok is False, "tmux / asking refused", msg[:44])
        r.check(not pane_has("ASKING GECMEMELI"), "tmux / nothing was typed into the pane")

        ok, msg, _ = try_send(pane, "asking", force=True, text="FORCE GECMELI")
        r.check(ok is True, "tmux / asking + force", msg[:44])
        r.check(pane_has("FORCE GECMELI"), "tmux / the text reached the pane")

        ok, msg, _ = try_send(pane, "waiting", text="WAITING GECMEMELI")
        r.check(ok is False, "tmux / waiting refused", msg[:44])

        ok, msg, _ = try_send(pane, "idle", text="IDLE GECMELI")
        r.check(ok is True, "tmux / idle", msg[:44])
    finally:
        subprocess.run(["tmux", "kill-session", "-t", SESSION],
                       capture_output=True)

sys.exit(r.finish())
