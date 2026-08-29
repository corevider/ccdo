#!/usr/bin/env python3
"""The inbox is pinned at the left edge of the tab strip.

Its page therefore has to come first in the session list, whatever the
discovery order was, and it must appear exactly once.
"""
from harness import jd, Results

r = Results("pinned inbox tab")

live = [{"target": "a:1", "label": "a", "live": True},
        {"target": "b:2", "label": "b", "live": False}]
sessions = jd.with_inbox(live)

r.check(sessions[0]["target"] == jd.INBOX, "the inbox comes first")
r.check([s["target"] for s in sessions[1:]] == ["a:1", "b:2"],
        "the other sessions keep their order")
r.check(sum(s["target"] == jd.INBOX for s in jd.with_inbox(sessions)) == 1,
        "adding the inbox twice still yields one inbox")
r.check(jd.with_inbox([])[0]["label"] == "ideabox" and jd.with_inbox([])[0]["live"],
        "the inbox is a live tab called ideabox")
r.check(live == [{"target": "a:1", "label": "a", "live": True},
                 {"target": "b:2", "label": "b", "live": False}],
        "the input list is left untouched")

# Ctrl+Tab and the wheel walk the session tabs only; the inbox has its own
# pinned button and Ctrl+1.
r.check(jd.next_page_index(0, 3, +1) == 1, "a step forward")
r.check(jd.next_page_index(2, 3, +1) == 0, "the last tab wraps to the first")
r.check(jd.next_page_index(0, 3, -1) == 2, "the first tab wraps to the last")
r.check(jd.next_page_index(None, 3, +1) == 0, "from the inbox, forward lands on the first")
r.check(jd.next_page_index(None, 3, -1) == 2, "from the inbox, back lands on the last")
r.check(jd.next_page_index(None, 0, +1) is None, "no session tabs, nowhere to go")

raise SystemExit(r.finish())
