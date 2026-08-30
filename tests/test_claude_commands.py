#!/usr/bin/env python3
"""/rename and /color from ccdo, and the directory that late records lacked.

The commands are typed into the session's pane; only an idle pane may be
typed at, since a busy one is mid-turn and a waiting one holds a question.
"""
from harness import jd, Results, CFG

r = Results("Claude Code commands")

r.check(jd.slash_rename("auth refactor!") == "/rename auth-refactor",
        "spaces and odd characters become hyphens")
r.check(jd.slash_rename("  ") == "" and jd.slash_rename("***") == "",
        "an empty name sends nothing")
r.check(jd.slash_color("Blue") == "/color blue" and jd.slash_color("default") == "/color default",
        "a known color, any case")
r.check(jd.slash_color("mauve") == "", "an unknown color sends nothing")

idle = {"target": "%9", "live": True, "state": "idle"}
r.check(jd.can_take_command(idle), "an idle pane takes a command")
r.check(jd.can_take_command(dict(idle, state="unknown")), "so does a scanned pane of unknown state")
for state in ("busy", "waiting", "asking"):
    r.check(not jd.can_take_command(dict(idle, state=state)), "not while %s" % state)
r.check(not jd.can_take_command(dict(idle, live=False)), "not a closed session")
r.check(not jd.can_take_command(dict(idle, target="sid:abc")), "not a session with no pane")

sent = []
real = jd.send_tmux
jd.send_tmux = lambda cfg, target, payload: (sent.append((target, payload, cfg.get("auto_enter"))), (True, "ok"))[1]
try:
    jd.send_claude_command(dict(CFG, auto_enter=False), "%9", "/color blue")
    ok, msg = jd.send_claude_command(CFG, "%9", "")
finally:
    jd.send_tmux = real
r.check(sent == [("%9", "/color blue", True)],
        "the command is typed and submitted even with auto_enter off", str(sent))
r.check(ok is False and not sent[1:], "an empty command is not typed")

# A record made by a later hook learns its directory from the next event.
reg = jd.Registry()
reg.drop("late-cwd")
reg.upsert("late-cwd", target="%7", state="busy")
jd.hook_user_prompt(CFG, jd.Store(CFG), reg, {"session_id": "late-cwd", "cwd": "/home/you/dev/late"})
rec = reg.get("late-cwd")
r.check(rec.get("cwd") == "/home/you/dev/late" and rec.get("label") == "late",
        "the directory and a label are filled in", str(rec))
jd.hook_user_prompt(CFG, jd.Store(CFG), reg, {"session_id": "late-cwd", "cwd": "/somewhere/else"})
r.check(reg.get("late-cwd").get("cwd") == "/home/you/dev/late",
        "a directory already known is not overwritten")

raise SystemExit(r.finish())
