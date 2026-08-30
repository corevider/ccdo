#!/usr/bin/env python3
"""Emptying a closed session's queue, and sending notes back to the inbox.

A tab for a session that has ended only stays because its queue is not
empty. Closing it must lose nothing: waiting notes return to the inbox,
sent ones are archived as done.
"""
from harness import jd, Results, CFG

r = Results("closing a session's queue")
store = jd.Store(CFG)
for t in store.all():
    store.delete(t["id"])

waiting = store.add("still waiting", target="gone:1")
sent = store.add("already handed over", target="gone:1")
store.update(sent["id"], status="sent", sent_at=jd.now_iso())
other = store.add("someone else's note", target="alive:2")
inbox_note = store.add("an inbox note")

r.check(store.move_to_inbox("alive:2") == 1, "a waiting note moves to the inbox")
moved = next(t for t in store.all() if t["id"] == other["id"])
r.check(not moved.get("target") and moved["status"] == "pending",
        "it keeps its status and loses its target")

moved_n, finished_n = store.close_target("gone:1")
r.check((moved_n, finished_n) == (1, 1), "one note moved, one archived", str((moved_n, finished_n)))
left = {t["id"]: t for t in store.all()}
r.check(waiting["id"] in left and not left[waiting["id"]].get("target"),
        "the waiting note is in the inbox")
r.check(sent["id"] not in left, "the sent note left the queue")
r.check(any(rec["task"]["id"] == sent["id"] for rec in jd.read_history()),
        "the sent note is in the history")
r.check("gone:1" not in store.active_targets(), "nothing keeps the tab alive")
r.check(inbox_note["id"] in left, "inbox notes are untouched")

raise SystemExit(r.finish())
