#!/usr/bin/env python3
"""Tasks that leave the queue must be written to the history.

Completed ones used to pile up in queue.json forever while deleted ones
vanished without a trace. Both now land in history.jsonl and leave the queue;
HISTORY.md is the readable form.
"""
import json
import os
import sys

from harness import jd, Results, CFG

store = jd.Store(CFG)
r = Results("history records")


def history_events():
    return [(rec["event"], rec["task"]["id"]) for rec in jd.read_history()]


# --- a completed task -----------------------------------------------------
t1 = store.add("a task to complete", target="sid:x")
store.update(t1["id"], status="done")

r.check(all(t["id"] != t1["id"] for t in store.all()),
        "a completed task left the queue")
r.check(("done", t1["id"]) in history_events(), "gecmiste 'done' kaydi var")

# --- a deleted task -------------------------------------------------------
t2 = store.add("a task to delete", target="sid:x")
store.delete(t2["id"])

r.check(all(t["id"] != t2["id"] for t in store.all()),
        "a deleted task left the queue")
r.check(("deleted", t2["id"]) in history_events(), "gecmiste 'deleted' kaydi var")

# Silinen gorevin METNI de duruyor olmali: sadece id tutmak gecmisi
# okunamaz hale getirirdi.
rec = [x for x in jd.read_history() if x["task"]["id"] == t2["id"]][0]
r.check(rec["task"]["text"] == "a task to delete", "the deleted task's text was kept")
r.check(bool(rec.get("ts")), "the record carries a timestamp", rec.get("ts", ""))

# --- a pending task must be left alone ------------------------------------
t3 = store.add("a pending task", target="sid:x")
r.check(any(t["id"] == t3["id"] for t in store.all()), "a pending task stays in the queue")
r.check(all(i != t3["id"] for _, i in history_events()), "a pending task is not in the history")

# --- append-only: earlier records are never removed -----------------------
before = len(jd.read_history())
store.update(t3["id"], status="done")
after = jd.read_history()
r.check(len(after) == before + 1, "every event appends one line")
r.check([e for e, _ in history_events()].count("done") == 2,
        "earlier records are still there")

# --- purge_done also moves done tasks left by an older version ------------
legacy = store.add("left over from an older version", target="sid:x")
with jd.FileLock(jd.LOCK_PATH):                 # dogrudan 'done' yaz
    data = json.load(open(jd.STORE_PATH, encoding="utf-8"))
    for t in data["tasks"]:
        if t["id"] == legacy["id"]:
            t["status"] = "done"
    json.dump(data, open(jd.STORE_PATH, "w", encoding="utf-8"))

moved = store.purge_done()
r.check(moved == 1, "purge_done returns how many moved", "moved=%s" % moved)
r.check(("done", legacy["id"]) in history_events(), "a legacy done task was moved to the history")

# Tasima anini damga olarak yazmak zaman cizgisini yanlis gosterirdi:
# The task was completed long ago and only moved today.
rec = [x for x in jd.read_history() if x["task"]["id"] == legacy["id"]][0]
r.check(rec["ts"] == legacy["created_at"],
        "a moved task keeps its own stamp", rec["ts"])

# --- a malformed line must not break the history --------------------------
with open(jd.HISTORY_PATH, "a", encoding="utf-8") as f:
    f.write("this is not json\n\n")
r.check(len(jd.read_history()) == len(after) + 1,
        "a malformed line is skipped, the rest are read")

# --- the markdown output --------------------------------------------------
jd.export_history_markdown()
md = open(jd.HISTORY_MD, encoding="utf-8").read()
r.check(os.path.exists(jd.HISTORY_MD), "HISTORY.md was produced")
r.check("a task to delete" in md and "a task to complete" in md,
        "the markdown carries the task texts")
r.check("✕" in md and "✓" in md, "deleted and completed are told apart")

# --- filtering by session (the window section uses this) ------------------
mine = store.add("bu oturuma ait", target="sid:filter-a")
other = store.add("baska oturuma ait", target="sid:filter-b")
loose = store.add("hedefsiz not")                       # ideabox
for t in (mine, other, loose):
    store.update(t["id"], status="done")

ids_a = [rec["task"]["id"] for rec in jd.history_for_target("sid:filter-a")]
r.check(mine["id"] in ids_a and other["id"] not in ids_a,
        "the session filter returns only its own tasks")

ids_inbox = [rec["task"]["id"] for rec in jd.history_for_target(jd.INBOX)]
r.check(loose["id"] in ids_inbox and mine["id"] not in ids_inbox,
        "untargeted tasks land in the inbox")

recs = jd.history_for_target("sid:filter-a")
r.check(recs[0]["task"]["id"] == mine["id"], "newest first")

r.check(len(jd.history_for_target("sid:filter-a", limit=1)) == 1,
        "the limit is applied")

# --- the cache must refresh when the file changes -------------------------
before = len(jd.read_history())
fresh = store.add("cache test", target="sid:filter-a")
store.update(fresh["id"], status="done")
r.check(len(jd.read_history()) == before + 1,
        "a new record is seen without the cache getting in the way")

# It must not hand out the internal list: mutating it would corrupt the cache
snap = jd.read_history()
snap.clear()
r.check(len(jd.read_history()) == before + 1, "the returned list is a copy")

sys.exit(r.finish())
