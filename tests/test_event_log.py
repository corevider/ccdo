#!/usr/bin/env python3
"""The decision log: why a task did not go should be readable from the log.

The auto chain used to stop silently once the budget was spent, and the user
had no way to see why nothing arrived. Every delivery decision is now written
to events.jsonl with its reason, and while the queue waits the window shows
the last obstacle in its notice line.
"""
from harness import jd, Results, CFG

r = Results("decision log")

TGT = "sid:log-test"


def reset():
    try:
        open(jd.EVENTS_PATH, "w").close()
    except OSError:
        pass
    reg = jd.Registry()
    reg.drop("logsid")
    store = jd.Store(CFG)
    for t in store.pending(TGT):
        store.delete(t["id"])
    return store, reg


def stop(cfg, store, reg):
    return jd.hook_stop(cfg, store, reg,
                        {"session_id": "logsid", "transcript_path": ""}) or {}


def kinds():
    return [e["kind"] for e in jd.read_events(target=TGT)]


# -------------------------------------------------------------- auto is off

cfg = dict(CFG, auto_advance=False, max_auto_advance=3)
store, reg = reset()
reg.upsert("logsid", target=TGT, cwd="/tmp/log-test", state="busy",
           auto_advance=False)
store.add("pending work", target=TGT)
stop(cfg, store, reg)
r.check(kinds() == ["skip_auto_off"], "with auto off the reason is recorded", str(kinds()))

stop(cfg, store, reg)
stop(cfg, store, reg)
r.check(kinds() == ["skip_auto_off"],
        "the same reason is not repeated back to back", str(kinds()))

r.check("auto is off" in (jd.last_block_reason(TGT) or ""),
        "the window can read the last obstacle", jd.last_block_reason(TGT))


# ------------------------------------------------------------------ budget

cfg = dict(CFG, auto_advance=True, max_auto_advance=2)
store, reg = reset()
reg.upsert("logsid", target=TGT, cwd="/tmp/log-test", state="busy",
           auto_advance=True)
for i in (1, 2, 3):
    store.add("task %d" % i, target=TGT)

for _ in range(3):
    stop(cfg, store, reg)
r.check(kinds() == ["advance", "advance", "skip_budget"],
        "handovers and the stop reason are recorded in order", str(kinds()))

last = jd.read_events(target=TGT)[-1]
r.check(last["used"] == 2 and last["cap"] == 2, "the budget numbers are in the record")
text = jd.describe_event(last)
r.check("budget spent (2/2)" in text and "once you type" in text,
        "the reason is rendered in plain words", text)
r.check(jd.last_block_reason(TGT) == text, "the window notice uses the same text")

r.check(jd.read_events(target=TGT)[0]["task_text"] == "task 1",
        "the log also keeps which task it was")

jd.hook_user_prompt(cfg, store, reg, {"session_id": "logsid"})
reg.upsert("logsid", state="busy")
stop(cfg, store, reg)
r.check(kinds()[-1] == "advance", "the chain resumes once the user types")
r.check(jd.last_block_reason(TGT) is None,
        "a successful delivery voids the old reason")


# ---------------------------------------------------------------- delivery

store, reg = reset()
task = store.add("a task for a closed session", target=TGT)
reg.upsert("logsid", target=TGT, cwd="/tmp/log-test", state="ended")
ok, msg = jd.deliver(CFG, store, task)
r.check(not ok and kinds() == ["fail"], "a failed delivery lands in the log", str(kinds()))
r.check("session ended" in jd.describe_event(jd.read_events(target=TGT)[-1]),
        "the reason comes from the delivery message itself")

r.check(jd.read_events(limit=1, target="olmayan-hedef") == [],
        "records from another target do not leak in")

raise SystemExit(r.finish())
