#!/usr/bin/env python3
"""The status line: what ccdo keeps of it, and how it shows in the window.

Claude Code pipes a JSON document to one statusline command. ccdo takes the
few numbers worth showing, keeps them on the session's registry record, and
hands the same JSON on to whatever drew the status line before — so the
terminal keeps its line and the window gains model, context, cost and limits.
"""
import io
import json
import sys

from harness import jd, Results

r = Results("status line")

SAMPLE = {
    "session_id": "sl-test",
    "model": {"id": "claude-fable-5", "display_name": "Fable 5"},
    "workspace": {"current_dir": "/home/you/dev/x", "git_worktree": "disco-button"},
    "cost": {"total_cost_usd": 9.3212, "total_duration_ms": 45000,
             "total_lines_added": 185, "total_lines_removed": 92},
    "context_window": {"total_input_tokens": 15500, "total_output_tokens": 1200,
                       "context_window_size": 200000, "used_percentage": 62.4,
                       "remaining_percentage": 37.6,
                       "current_usage": {"input_tokens": 8500, "output_tokens": 1200,
                                         "cache_creation_input_tokens": 5000,
                                         "cache_read_input_tokens": 111600}},
    "effort": {"level": "high"},
    "rate_limits": {"five_hour": {"used_percentage": 30.0, "resets_at": 1000000 + 9900},
                    "seven_day": {"used_percentage": 36.4, "resets_at": 1500000}},
}

st = jd.statusline_summary(SAMPLE)
r.check(st["model"] == "Fable 5" and st["effort"] == "high", "model and effort are read")
r.check(st["ctx_pct"] == 62 and st["ctx_tokens"] == 125100,
        "context is the percentage and the tokens of the last call", str(st))
r.check(st["five_hour_pct"] == 30 and st["seven_day_pct"] == 36,
        "the rate limits are rounded percentages")
r.check(st["worktree"] == "disco-button", "the worktree name is kept")

chips = jd.status_chips(st, now=1000000)
r.check(chips[0] == "Fable 5 · high", "the first chip is the model", str(chips))
r.check("ctx 125.1k · 62%" in chips, "context shows tokens and percentage", str(chips))
r.check("$9.32" in chips, "cost to the cent", str(chips))
r.check("5h 30% · 7d 36%" in chips, "both limit windows on one chip", str(chips))
r.check("reset 2h 45m" in chips, "time until the five-hour window resets", str(chips))
r.check("+185 −92" in chips and "⎇ disco-button" in chips, "lines and worktree", str(chips))
r.check(jd.status_chips({}) == [] and jd.status_chips(None) == [],
        "no status, no chips")
r.check(jd.status_chips(jd.statusline_summary({"model": {"display_name": "Opus"}})) == ["Opus"],
        "a sparse document yields only what it has")

rows = jd.chip_rows(chips)
r.check(rows[0][0] == "Fable 5 · high" and sum(map(len, rows)) == len(chips)
        and all(sum(len(c) + 5 for c in row) <= 62 for row in rows),
        "the chips break into rows that fit the card", str(rows))
r.check(jd.chip_rows([]) == [] and jd.chip_rows(["x" * 80]) == [["x" * 80]],
        "an empty list has no rows; one oversize chip still gets its row")

r.check(jd.short_tokens(999) == "999" and jd.short_tokens(3200000) == "3.2M",
        "token counts are shortened")
r.check(jd.short_countdown(-5) == "" and jd.short_countdown(38 * 60) == "38m"
        and jd.short_countdown(26 * 3600) == "1d 2h", "countdowns read well")

# --- settings.json: the previous status line keeps drawing ---------------
settings = {"statusLine": {"type": "command", "command": "npx -y ccstatusline@latest",
                           "padding": 0, "refreshInterval": 10}}
r.check(jd.wrap_statusline(settings, "/usr/bin/ccdo") is True, "wrapping changes settings")
r.check(settings["statusLine"]["command"] == "/usr/bin/ccdo statusline -- npx -y ccstatusline@latest"
        and settings["statusLine"]["refreshInterval"] == 10,
        "the old command follows --, the other keys stay", str(settings))
r.check(jd.wrap_statusline(settings, "/usr/bin/ccdo") is False, "wrapping twice is a no-op")
bare = {}
jd.wrap_statusline(bare, "/usr/bin/ccdo")
r.check(bare["statusLine"] == {"type": "command", "command": "/usr/bin/ccdo statusline"},
        "with no status line ccdo draws its own")

# --- the command itself: keeps the summary, passes the JSON through ------
reg = jd.Registry()
reg.drop("sl-test")
reg.upsert("sl-test", target="sid:sl", cwd="/home/you/dev/x", state="busy")
real_in, real_out = sys.stdin, sys.stdout
sys.stdin, sys.stdout = io.StringIO(json.dumps(SAMPLE)), io.StringIO()
try:
    rc = jd.run_statusline(["--", "cat"])
    echoed = sys.stdout.getvalue()
finally:
    sys.stdin, sys.stdout = real_in, real_out
r.check(rc == 0 and json.loads(echoed)["session_id"] == "sl-test",
        "the JSON reaches the previous command untouched")
r.check((reg.get("sl-test").get("status") or {}).get("model") == "Fable 5",
        "the summary lands on the session's record")

sys.stdin, sys.stdout = io.StringIO(json.dumps(dict(SAMPLE, session_id="nobody"))), io.StringIO()
try:
    jd.run_statusline([])
    own = sys.stdout.getvalue()
finally:
    sys.stdin, sys.stdout = real_in, real_out
r.check(own.startswith("Fable 5 · high | ctx"), "without a command ccdo draws a line itself", own)
r.check(reg.get("nobody") is None, "an unknown session gets no registry record")

sys.stdin, sys.stdout = io.StringIO("not json"), io.StringIO()
try:
    rc = jd.run_statusline(["--", "cat"])
finally:
    sys.stdin, sys.stdout = real_in, real_out
r.check(rc == 0, "bad input never costs the user the status line")

raise SystemExit(r.finish())
