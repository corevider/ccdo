#!/usr/bin/env python3
"""Auto-advance: the chain must not break, the preference must not vanish.

Two separate faults:

1. hook_stop returned early the moment it saw Claude Code's stop_hook_active
   flag. That flag is also set on the Stop that follows a task the hook itself
   handed over, so the chain always broke at the first task and the
   max_auto_advance budget could never be spent. The budget is now the guard.
2. The 'auto' preference was stored per session_id, and a Claude restart minted
   a new one — so the switch quietly turned itself off. The preference now
   belongs to the working directory.
"""
import os

from harness import jd, Results, CFG

r = Results("auto-advance")

CWD = "/home/you/dev/example"


def fresh(sid, auto=True, count=0):
    reg = jd.Registry()
    reg.drop(sid)
    reg.upsert(sid, target="sid:" + sid, cwd=CWD, state="busy",
               auto_advance=auto, advance_count=count)
    return reg


def stop(cfg, store, reg, sid, active):
    out = jd.hook_stop(cfg, store, reg, {"session_id": sid, "transcript_path": "",
                                         "stop_hook_active": active}) or {}
    return (out.get("reason") or "").strip()


# ------------------------------------------------------------------- chain

cfg = dict(CFG, auto_advance=True, max_auto_advance=3)
store = jd.Store(cfg)
SID = "auto-chain"
reg = fresh(SID)
for t in store.pending("sid:" + SID):
    store.delete(t["id"])
for i in range(1, 6):
    store.add("task %d" % i, target="sid:" + SID)

got = [stop(cfg, store, reg, SID, False)]
got += [stop(cfg, store, reg, SID, True) for _ in range(3)]
r.check(got[:3] == ["task 1", "task 2", "task 3"],
        "the chain no longer trips on stop_hook_active", " | ".join(got[:3]))
r.check(got[3] == "", "it stops once the budget is spent (max_auto_advance)", repr(got[3]))
r.check(reg.get(SID)["advance_count"] == 3, "the counter tracks what was spent")

jd.hook_user_prompt(cfg, store, reg, {"session_id": SID})
r.check(reg.get(SID)["advance_count"] == 0, "a user message resets the budget")
reg.upsert(SID, state="busy")
r.check(stop(cfg, store, reg, SID, False) == "task 4",
        "the chain resumes on the next turn")

reg = fresh(SID, auto=False)
r.check(stop(cfg, store, reg, SID, False) == "",
        "with auto off nothing is handed over")

for t in store.pending("sid:" + SID):
    store.delete(t["id"])


# -------------------------------------------------------------- preference

prefs = jd.AutoPrefs()
r.check(prefs.get(CWD) is None, "a directory never set has no preference")

reg = jd.Registry()
reg.drop("old")
jd.hook_session_start(CFG, store, reg, {"session_id": "old", "cwd": CWD,
                                        "transcript_path": ""})
r.check(reg.get("old")["auto_advance"] is None,
        "with no preference the session is left on the global default")

prefs.set(CWD, True)
reg.drop("new")
jd.hook_session_start(CFG, store, reg, {"session_id": "new", "cwd": CWD,
                                        "transcript_path": ""})
r.check(reg.get("new")["auto_advance"] is True,
        "a new session_id inherits the preference from the directory")

reg.drop("sub")
jd.hook_session_start(CFG, store, reg, {"session_id": "sub",
                                        "cwd": os.path.join(CWD, "tests", "x"),
                                        "transcript_path": ""})
r.check(reg.get("sub")["auto_advance"] is True, "a subdirectory inherits it too")

prefs.set(os.path.join(CWD, "tests"), False)
r.check(prefs.get(os.path.join(CWD, "tests", "x")) is False,
        "the longest matching path wins (a subdirectory does not override)")
r.check(prefs.get(CWD) is True, "the parent preference is untouched")

r.check(prefs.get("/home/you/dev/other") is None,
        "a sibling directory does not inherit")
r.check(prefs.get(CWD + "-twin") is None,
        "a directory sharing a name prefix does not inherit")
r.check(prefs.get(None) is None, "a missing cwd causes no trouble")

prefs.set(CWD, False)
reg.drop("off")
jd.hook_session_start(CFG, store, reg, {"session_id": "off", "cwd": CWD,
                                        "transcript_path": ""})
r.check(reg.get("off")["auto_advance"] is False,
        "once switched off, a new session starts off too")

raise SystemExit(r.finish())
