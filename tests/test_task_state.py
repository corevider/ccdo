#!/usr/bin/env python3
"""The colored bar on a task row tells which stage the task is at.

Queued, sent, working and done come from one table; 'working' is reserved
for the latest sent task while its session is busy, since Claude Code reads
one note at a time.
"""
from harness import jd, Results

r = Results("task state indicator")

busy = {"target": "a:1", "live": True, "state": "busy"}
idle = {"target": "a:1", "live": True, "state": "idle"}
gone = {"target": "a:1", "live": False, "state": "busy"}

pending = {"id": "p1", "status": "pending"}
old = {"id": "s1", "status": "sent", "sent_at": "2026-08-29T10:00:00"}
new = {"id": "s2", "status": "sent", "sent_at": "2026-08-29T11:00:00"}
done = {"id": "d1", "status": "done"}

latest = jd.latest_sent_id([pending, old, new])
r.check(latest == "s2", "the latest sent task is the one handed over last", latest)
r.check(jd.latest_sent_id([pending]) is None, "no sent task, no latest one")

r.check(jd.task_state(pending, busy, latest) == "queued", "a pending task is queued")
r.check(jd.task_state(new, busy, latest) == "working",
        "the latest sent task is working while the session is busy")
r.check(jd.task_state(old, busy, latest) == "sent",
        "an older sent task stays sent even when the session is busy")
r.check(jd.task_state(new, idle, latest) == "sent",
        "a sent task is just sent while the session is idle")
r.check(jd.task_state(new, gone, latest) == "sent",
        "a closed session works on nothing")
r.check(jd.task_state(new, None) == "sent", "no session facts: sent")
r.check(jd.task_state(done, busy) == "done", "a done task is done")

r.check(set(jd.TASK_STATES) >= {"queued", "sent", "working", "done"},
        "every stage has a word")
for theme in (jd.THEME_DARK, jd.THEME_LIGHT):
    r.check(all("state_%s" % k in theme for k in ("queued", "sent", "working", "done")),
            "every stage has a color in the palette")

# The row says when a sent task went out; the day only when it is not today.
from datetime import datetime, timedelta
now = datetime(2026, 8, 30, 15, 0).astimezone()
r.check(jd.sent_stamp(now.replace(hour=14, minute=32).isoformat(), now) == "14:32",
        "a task sent today shows the time only")
earlier = (now - timedelta(days=1)).replace(hour=9, minute=5)
r.check(jd.sent_stamp(earlier.isoformat(), now) == "29 Aug 09:05",
        "a task sent on another day shows the day too")
r.check(jd.sent_stamp(None, now) == "" and jd.sent_stamp("bozuk", now) == "",
        "no usable time, no stamp")

raise SystemExit(r.finish())
