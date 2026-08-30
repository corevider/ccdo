#!/usr/bin/env python3
"""A handed-over note is finished when the turn it started ends.

Nothing used to close a sent note: it stayed 'sent' until someone clicked ✓,
and 'working' was guessed from the session being busy. The hooks now record
which note a session is on and archive it at the Stop that follows — unless
that turn ended in a question, which keeps the note open for the answer.
"""
from harness import jd, Results, CFG

r = Results("task lifecycle")

cfg = dict(CFG, auto_advance=True, max_auto_advance=5)
store = jd.Store(cfg)
SID = "life-cycle"
TARGET = "sid:" + SID
reg = jd.Registry()
reg.drop(SID)
reg.upsert(SID, target=TARGET, cwd="/home/you/dev/x", state="busy",
           auto_advance=True, advance_count=0)
for t in store.all():
    if t.get("target") == TARGET:
        store.delete(t["id"])
first = store.add("first note", target=TARGET)
second = store.add("second note", target=TARGET)


def stop():
    return jd.hook_stop(cfg, store, reg, {"session_id": SID, "transcript_path": ""}) or {}


stop()
r.check(reg.get(SID).get("current_task") == first["id"],
        "handing a note over records that the session is on it")
sess = {"target": TARGET, "live": True, "state": "busy",
        "current_task": reg.get(SID).get("current_task")}
r.check(jd.task_state(next(t for t in store.all() if t["id"] == first["id"]), sess) == "working",
        "the window shows that note as working")

real = jd.turn_ends_with_question
jd.turn_ends_with_question = lambda *a: (True, "asked")
try:
    stop()
finally:
    jd.turn_ends_with_question = real
r.check(any(t["id"] == first["id"] and t["status"] == "sent" for t in store.all()),
        "a turn that ends in a question leaves the note open")
r.check(reg.get(SID).get("current_task") == first["id"], "and the session stays on it")

jd.hook_user_prompt(cfg, store, reg, {"session_id": SID})
stop()
r.check(all(t["id"] != first["id"] for t in store.all()),
        "the next turn without a question finishes the note")
rec = next((h for h in jd.read_history() if h["task"]["id"] == first["id"]), None)
r.check(rec is not None and rec["event"] == "done" and rec["task"].get("finished_via") == "stop_hook",
        "it is in the history as done by the hook")
r.check(reg.get(SID).get("current_task") == second["id"],
        "and the session moved on to the next note")

# A note sent back to the ideabox meanwhile must not be finished.
store.update(second["id"], target=None, status="pending")
stop()
back = next(t for t in store.all() if t["id"] == second["id"])
r.check(back["status"] == "pending" and not back.get("target"),
        "a note taken back to the ideabox is left alone at the next Stop")

raise SystemExit(r.finish())
