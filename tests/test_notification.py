#!/usr/bin/env python3
"""The notification hook must not overwrite the 'asking' lock.

The idle notification arrived ~60s after Claude asked a question, set the
state to 'waiting' and opened the lock silently. Only the user's answer
(UserPromptSubmit) may lift it.
"""
import sys

from harness import jd, Results, CFG

SID = "test-notification-session"
reg = jd.Registry()
r = Results("notification hook and lock ownership")


def notify(kind, msg):
    jd.hook_notification(CFG, None, reg, {
        "session_id": SID, "notification_type": kind, "message": msg})
    return (reg.get(SID) or {}).get("state")


reg.upsert(SID, state="asking", target="sid:" + SID, cwd="/tmp/x")
r.check(notify("idle", "Claude is waiting for your input") == "asking",
        "asking + bosta-kalma bildirimi", "kilit korunuyor")

reg.upsert(SID, state="asking")
r.check(notify("permission", "Claude needs your permission to use Bash") == "asking",
        "asking + izin bildirimi", "kilit korunuyor")

# Kilit yokken bildirim normal calismali
reg.upsert(SID, state="busy")
r.check(notify("permission", "Claude needs your permission to use Bash") == "waiting",
        "busy + izin bildirimi", "waiting olmali")

reg.upsert(SID, state="busy")
r.check(notify("other", "something happened") == "busy", "busy + notr bildirim")

# Kilidi kaldiran tek sey: kullanicinin cevabi
reg.upsert(SID, state="asking")
jd.hook_user_prompt(CFG, None, reg, {"session_id": SID})
r.check((reg.get(SID) or {}).get("state") == "busy",
        "asking + the user answers", "kilit kalkiyor")

sys.exit(r.finish())
