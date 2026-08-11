#!/usr/bin/env python3
"""Tab and header labels: the session name and the folder must both show.

Claude Code produces the session name a few turns in. Once it arrived it took
over the header and the folder name disappeared entirely; the folder now sits
on the line below. While there is no name the label already falls back to the
folder, and in that case we do not repeat it.
"""
import sys

from harness import jd, Results

r = Results("session labels")


def sess(label, cwd="/home/you/dev/ccdo", target="sid:abc123",
         live=True, color_source="palet"):
    return {"label": label, "cwd": cwd, "target": target, "live": live,
            "color_source": color_source}


# --- the line below: folder + target ------------------------------------
line = jd.session_line(sess("Question detection"))
r.check("ccdo" in line and "sid:abc123" in line,
        "with a name, folder and target show together", line)

line = jd.session_line(sess("ccdo"))
r.check(line.count("ccdo") == 0, "a name equal to the folder is not repeated", line)

line = jd.session_line(sess("A name", live=False))
r.check("closed" in line, "a closed session is marked", line)

line = jd.session_line(sess("A name", color_source="claude"))
r.check("tema: claude" in line, "the color source is kept", line)

line = jd.session_line({"label": "ideabox", "cwd": "", "target": "__inbox__",
                        "live": True, "color_source": "palet"})
r.check("__inbox__" in line and "  ·  " not in line,
        "a session with no cwd leaves no empty part", line)

# --- tab label -----------------------------------------------------------
r.check(jd.session_tab_text(sess("short")) == "short", "a short name is not clipped")
long_name = jd.session_tab_text(sess("Question detection and the tmux lock"))
r.check(len(long_name) == 14 and long_name.endswith("…"),
        "a long name is clipped", long_name)

# --- tooltip -------------------------------------------------------------
tip = jd.session_tooltip(sess("Question detection"))
r.check(all(p in tip for p in ("Question detection", "ccdo", "sid:abc123")),
        "the tooltip carries name + folder + target", tip)

tip = jd.session_tooltip(sess("ccdo"))
r.check(tip.count("ccdo") == 1, "the folder is not repeated in the tooltip", tip)

# --- folder name ---------------------------------------------------------
r.check(jd.session_folder({"cwd": "/home/you/dev/ccdo/"}) == "ccdo",
        "a trailing slash makes no difference")
r.check(jd.session_folder({"cwd": ""}) == "", "no cwd means empty")

# --- state mark (left of the name on the tab) ----------------------------
def st(state=None, live=True):
    s = sess("A session")
    s["live"] = live
    if state:
        s["state"] = state
    return s


r.check(jd.state_mark(st("asking")) == jd.text_glyph("❓"), "asked a question -> ❓")
r.check(jd.state_mark(st("idle")) == jd.text_glyph("✓"), "finished its work -> ✓")
r.check(jd.state_mark(st("busy")) == jd.text_glyph("●"), "running -> ●")
r.check(jd.state_mark(st("waiting")) == jd.text_glyph("⚠"), "waiting on a prompt -> ⚠")
r.check(jd.state_mark(st("ended")) == jd.text_glyph("·"), "ended -> ·")

# A closed session carries no state but must still read as closed
r.check(jd.state_mark(st(None, live=False)) == jd.text_glyph("·"), "not live -> ·")

# Virtual tabs with no state, like the inbox, carry no mark
r.check(jd.state_mark({"label": "ideabox", "live": True}) == "",
        "a stateless tab carries no mark")

# The page header and the tab mark must come from the same table
r.check(jd.state_text(st("asking")) == jd.text_glyph("❓") + " asked a question",
        "the header words match", jd.state_text(st("asking")))
r.check(jd.state_text(st("asking")).startswith(jd.state_mark(st("asking"))),
        "header and tab use the same mark")
r.check(jd.state_text({"label": "ideabox", "live": True}) == "",
        "a stateless tab has empty header words")

# --- wheel-to-tab direction ----------------------------------------------
r.check(jd.scroll_step("down") == 1, "down -> forward")
r.check(jd.scroll_step("up") == -1, "up -> back")
r.check(jd.scroll_step("right") == 1, "right -> forward")
r.check(jd.scroll_step("left") == -1, "left -> back")

# Modern mice send "smooth"; the direction is in the deltas
r.check(jd.scroll_step("smooth", 0.0, 1.5) == 1, "smooth dy>0 -> forward")
r.check(jd.scroll_step("smooth", 0.0, -1.5) == -1, "smooth dy<0 -> back")
r.check(jd.scroll_step("smooth", 2.0, 0.0) == 1, "horizontal wheel dx>0 -> forward")
r.check(jd.scroll_step("smooth", 0.0, 0.0) == 0, "no delta means no move")
r.check(jd.scroll_step("") == 0, "an unknown direction is ignored")

sys.exit(r.finish())
