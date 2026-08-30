#!/usr/bin/env python3
"""The 'open terminal' button: which terminal, with what, for which session."""
from harness import jd, Results, CFG

r = Results("open the session's terminal")

have = {"kitty", "x-terminal-emulator"}
argv = jd.terminal_argv(CFG, "tmux attach -t x", which=lambda exe: exe in have)
r.check(argv == ["kitty", "-e", "sh", "-c", "tmux attach -t x"] or jd.IS_MAC,
        "auto takes the first terminal installed, in preference order", str(argv))
argv = jd.terminal_argv(CFG, "tmux attach -t x", which=lambda exe: False)
r.check(argv is None or jd.IS_MAC, "nothing installed, nothing to run")
argv = jd.terminal_argv(dict(CFG, terminal_command="foot -e sh -c {cmd}"), "tmux attach -t x")
r.check(argv == ["foot", "-e", "sh", "-c", "tmux attach -t x"],
        "a configured command gets the command as one argument", str(argv))
argv = jd.terminal_argv(dict(CFG, terminal_command='"/opt/My Term/term" -e {cmd}'), "tmux attach -t x")
r.check(argv[0] == "/opt/My Term/term", "the setting is split like a shell would", str(argv))

r.check(jd.tmux_session_of("proj:0.0") == "proj", "a session:window.pane target names its session")
r.check(jd.tmux_session_of("") == "", "no target, no session")

ok, msg = jd.open_session_terminal(CFG, "sid:no-pane")
r.check(ok is True or "tmux" in msg or "terminal" in msg,
        "a target without a pane fails with a reason rather than an error", msg)

raise SystemExit(r.finish())
