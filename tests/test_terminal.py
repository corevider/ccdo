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

spawned = []
real_popen = jd.subprocess.Popen
jd.subprocess.Popen = lambda argv, **kw: spawned.append(argv)
try:
    for bad in ("sid:no-pane", jd.INBOX, ""):
        ok, msg = jd.open_session_terminal(CFG, bad)
        r.check(ok is False and not spawned,
                "no terminal opens for %r — there is no pane to show" % bad, msg)
finally:
    jd.subprocess.Popen = real_popen
r.check(not jd.is_tmux_target(jd.INBOX) and not jd.is_tmux_target("sid:x")
        and jd.is_tmux_target("%3") and jd.is_tmux_target("proj:0.0"),
        "only a pane counts as a tmux target")

raise SystemExit(r.finish())
