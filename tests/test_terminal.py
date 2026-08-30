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

# --- how the window that already shows the session is found ---------------
r.check(jd.title_names_session('cc-api:0:claude - "…"', "cc-api")
        and jd.title_names_session("cc-api", "cc-api")
        and not jd.title_names_session("cc-api-2:0:claude", "cc-api")
        and not jd.title_names_session("", "cc-api"),
        "a tmux title names its session, and only its own")
r.check(jd.terminal_app_id.__doc__ and jd.TERMINAL_APP_IDS["ptyxis"] == "org.gnome.Ptyxis",
        "terminals map to their desktop ids")

calls = []
real = {n: getattr(jd, n) for n in ("tmux_session_of", "run_cmd", "raise_terminal_window",
                                     "focus_terminal_via_shell", "show_in_recent_client",
                                     "terminal_argv")}
jd.tmux_session_of = lambda t: "cc-x"
jd.run_cmd = lambda args, timeout=10: (calls.append(args), (0, "", ""))[1]
jd.terminal_argv = lambda cfg, cmd, which=None: ["fake-term", cmd]
spawned = []
real_popen = jd.subprocess.Popen
jd.subprocess.Popen = lambda argv, **kw: spawned.append(argv)


def chain(x11, shell, recent):
    calls.clear(); spawned.clear()
    jd.raise_terminal_window = lambda s: (calls.append("x11"), x11)[1]
    jd.focus_terminal_via_shell = lambda s: (calls.append("shell"), shell)[1]
    jd.show_in_recent_client = lambda cfg, s, token: (calls.append(("recent", token)), recent)[1]
    ok, msg = jd.open_session_terminal(CFG, "%9", token="tok")
    return ok, [c for c in calls if isinstance(c, (str, tuple))], list(spawned)


try:
    ok, steps, sp = chain(True, True, True)
    r.check(ok and steps == ["x11"] and not sp, "X11: the attached window comes up, nothing else runs", str(steps))
    ok, steps, sp = chain(False, True, True)
    r.check(ok and steps == ["x11", "shell"] and not sp, "the extension is tried next", str(steps))
    ok, steps, sp = chain(False, False, True)
    r.check(ok and steps == ["x11", "shell", ("recent", "tok")] and not sp,
            "then the terminal comes up with the token and its last tab switches", str(steps))
    ok, steps, sp = chain(False, False, False)
    r.check(ok and sp == [["fake-term", "tmux attach -t cc-x"]],
            "and only then does a new terminal attach", str(sp))
    selected = [c for c in calls if isinstance(c, list) and c[:2] == ["tmux", "select-pane"]]
    r.check(selected == [["tmux", "select-pane", "-t", "%9"]], "the pane is selected first")
finally:
    for n, f in real.items():
        setattr(jd, n, f)
    jd.subprocess.Popen = real_popen

# Switching the last-used tab is a choice; off, the chain falls through.
jd.tmux_clients = lambda session=None: [{"tty": "/dev/pts/9", "activity": 5, "session": "other", "pid": "1"}]
r.check(jd.show_in_recent_client(CFG, "cc-x", "tok") is False,
        "switching the last-used tab is opt-in: off by default, the tab is left alone")
r.check(jd.show_in_recent_client(dict(CFG, terminal_switch_client=True), "cc-x", "") is False or jd.IS_MAC,
        "without a token the terminal cannot be raised, so nothing is switched")

raise SystemExit(r.finish())
