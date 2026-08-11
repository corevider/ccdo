#!/usr/bin/env python3
"""The color a session set with /color must reach its tab.

Claude Code writes that choice into the transcript as an
{"type":"agent-color","agentColor":...} entry. Since the color was chosen
deliberately for that one session, it outranks the project theme.
"""
import json
import os
import sys

from harness import jd, Results, tmp_path

r = Results("/color session color")


def write_transcript(name, colors, pad=0):
    """Icinde sirayla verilen agent-color girdileri olan bir transcript uret.

    pad: girdilerden SONRA eklenecek dolgu (bayt). Kuyruk penceresi disina
    used to push the entry out of the tail window.
    """
    p = tmp_path(name)
    with open(p, "wb") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user",
                                                        "content": "selam"}}).encode() + b"\n")
        for c in colors:
            f.write(json.dumps({"type": "agent-color", "agentColor": c,
                                "sessionId": "x"}).encode() + b"\n")
        while pad > 0:
            line = json.dumps({"type": "assistant", "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "x" * 400}]}}).encode() + b"\n"
            f.write(line)
            pad -= len(line)
    return p


# --- ad / bicim cozumleme -------------------------------------------------
r.check(jd.parse_agent_color("red") == "#cd3131", "name -> hex")
r.check(jd.parse_agent_color("  RED ") == "#cd3131", "whitespace and case")
r.check(jd.parse_agent_color("orange") == jd.AGENT_COLORS["orange"],
        "a non-ANSI name (orange)")
r.check(jd.parse_agent_color("#ff8800") == "#ff8800", "a hex literal")
r.check(jd.parse_agent_color("rgb(0,128,255)") == "#0080ff", "rgb()")
r.check(jd.parse_agent_color("bilinmeyenrenk") is None,
        "unknown name -> None (color falls back to the older route)")
r.check(jd.parse_agent_color(None) is None, "no value -> None")

# --- transcript'ten okuma -------------------------------------------------
p = write_transcript("color-basit.jsonl", ["red"])
r.check(jd.transcript_agent_color(p) == "#cd3131", "read out of the transcript")

p = write_transcript("color-son.jsonl", ["red", "blue", "green"])
r.check(jd.transcript_agent_color(p) == jd.AGENT_COLORS["green"],
        "the last entry wins")

p = write_transcript("color-yok.jsonl", [])
r.check(jd.transcript_agent_color(p) is None, "no entry -> None")
r.check(jd.transcript_agent_color(None) is None, "no path -> None")

# It must be found even if the color was set long ago and never rewritten:
# penceresinin disina itiyoruz.
p = write_transcript("color-uzak.jsonl", ["purple"], pad=400_000)
r.check(os.path.getsize(p) > 262144, "the file is larger than the tail window",
        "%d bayt" % os.path.getsize(p))
r.check(jd.transcript_agent_color(p) == jd.AGENT_COLORS["purple"],
        "absent from the tail, we scan from the start")

# The color must survive the entry leaving the tail (the file keeps growing)
p2 = tmp_path("color-yapiskan.jsonl")
os.replace(write_transcript("color-yapiskan-src.jsonl", ["teal"]), p2)
r.check(jd.transcript_agent_color(p2) == jd.AGENT_COLORS["teal"], "found first")
with open(p2, "ab") as f:
    f.write(b'{"type":"assistant","message":{"role":"assistant","content":[]}}\n')
r.check(jd.transcript_agent_color(p2) == jd.AGENT_COLORS["teal"],
        "the last known color survives a file change")

# --- oncelik --------------------------------------------------------------
p = write_transcript("color-oncelik.jsonl", ["red"])

color, fixed, src = jd.pick_color({}, "sid:a", "etiket", "/tmp/yok", p)
r.check((color, fixed, src) == ("#cd3131", True, "/color"),
        "/color paletten once geliyor", src)

cfg_ov = {"sessions": {"sid:a": {"color": "#123456"}}}
color, fixed, src = jd.pick_color(cfg_ov, "sid:a", "etiket", "/tmp/yok", p)
r.check((color, src) == ("#123456", "config"),
        "elle sabitlenen renk /color'dan once geliyor", src)

color, fixed, src = jd.pick_color({"use_claude_agent_color": False},
                                  "sid:a", "etiket", "/tmp/yok", p)
r.check(src == "palet", "switched off, it falls back to the palette", src)

color, fixed, src = jd.pick_color({}, "sid:b", "etiket", "/tmp/yok", None)
r.check(src == "palet", "no transcript -> palette", src)

sys.exit(r.finish())
