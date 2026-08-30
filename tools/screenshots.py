#!/usr/bin/env python3
"""Render the windows for the README.

    tools/screenshots.py [outdir]

Both palettes are rendered, so the README can follow the reader's theme.

The app is drawn offscreen with GTK, so these are the real widget trees with
the real stylesheet — only the window manager's frame is missing. Everything
is seeded here, so re-running it after a design change refreshes the images
without anyone having to arrange a desktop and crop a photo.

It works in a temporary XDG directory and never touches a real queue.
"""
import importlib.util
import os
import subprocess
import re
import shutil
import sys
import tempfile
import textwrap
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs")

TMP = tempfile.mkdtemp(prefix="ccdo-shots-")
os.environ["XDG_DATA_HOME"] = os.path.join(TMP, "data")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "config")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(TMP, "run")
os.environ.setdefault("LANG", "en_US.UTF-8")
for d in os.environ["XDG_DATA_HOME"], os.environ["XDG_CONFIG_HOME"], os.environ["XDG_RUNTIME_DIR"]:
    os.makedirs(d, exist_ok=True)

import gi                                                        # noqa: E402
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib                         # noqa: E402

spec = importlib.util.spec_from_file_location("ccdo", os.path.join(ROOT, "ccdo.py"))
jd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jd)
jd.ensure_dirs()
shutil.copytree(os.path.join(ROOT, "locales"),
                os.path.join(jd.DATA_DIR, "locales"), dirs_exist_ok=True)

SRC = open(os.path.join(ROOT, "ccdo.py"), encoding="utf-8").read()


def seed():
    """Two live sessions and a queue that shows what the window is for."""
    # The registry is isolated, but the tmux scan would still find real panes
    # on the machine building these — and put someone's actual session in a
    # screenshot. Match nothing, so only what we seed shows up.
    jd.atomic_write(jd.CONFIG_PATH, jd.json.dumps(
        {"process_match": ["__ccdo_none__"], "pane_match": ["__ccdo_none__"],
         "check_updates": False}, indent=2) + "\n")
    cfg = jd.load_config()
    store, reg = jd.Store(cfg), jd.Registry()
    reg.upsert("s1", target="%3", cwd="/home/you/dev/api", state="idle",
               label="api-server", title="api-server", auto_advance=True,
               status=jd.statusline_summary({
                   "model": {"display_name": "Fable 5"}, "effort": {"level": "high"},
                   "cost": {"total_cost_usd": 9.32, "total_lines_added": 185,
                            "total_lines_removed": 92},
                   "context_window": {"used_percentage": 62,
                                      "current_usage": {"input_tokens": 8500,
                                                        "cache_read_input_tokens": 116600}},
                   "rate_limits": {"five_hour": {"used_percentage": 30,
                                                 "resets_at": time.time() + 2 * 3600 + 45 * 60},
                                   "seven_day": {"used_percentage": 36}}}, "main"))
    reg.upsert("s2", target="sid:demo", cwd="/home/you/dev/web", state="busy",
               label="web-ui", title="web-ui")
    for text, priority in (
            ("Retry the upload once before giving up", 1),
            ("Split the parser out of the request handler", 0),
            ("The progress bar jumps back on slow connections", 0)):
        store.add(text, target="%3", priority=priority)
    sent = store.pending("%3")[-1]
    store.update(sent["id"], status="sent",
                 sent_at=jd.datetime.now().astimezone().replace(
                     hour=9, minute=41, second=0).isoformat(timespec="seconds"))
    store.add("Look into that flaky nightly build")
    store.add("Write down how the release script works")
    jd.log_event("skip_budget", target="%3",
                 task={"id": "x", "text": "Cache the search index"}, used=3, cap=3)
    jd.atomic_write(jd.UPDATE_PATH, '{"checked_at": 0, "latest": ""}\n')
    return cfg


def styled(widget_box, width, height, path):
    off = Gtk.OffscreenWindow()
    off.set_size_request(width, height)
    ground = Gtk.EventBox()
    for cls in ("jd-window", "jd-body"):
        ground.get_style_context().add_class(cls)
    ground.add(widget_box)
    off.add(ground)
    off.show_all()
    snap(off, path)
    return off


def snap(off, path):
    """Save the offscreen window as it is now; call again after a change."""
    for _ in range(4):
        while Gtk.events_pending():
            Gtk.main_iteration()
    off.get_pixbuf().savev(path, "png", [], [])
    print("  %s" % os.path.relpath(path, ROOT))


def note_window(out, theme):
    """Drive the real App, then render its notebook."""
    real_main = Gtk.main

    def render():
        win = next((w for w in Gtk.Window.list_toplevels()
                    if isinstance(w, Gtk.Window) and w.get_title() == "ccdo"), None)
        if win is None:
            Gtk.main_quit()
            return False
        child = win.get_child()
        win.remove(child)
        off = styled(child, 560, 700,
                     os.path.join(out, "note-window-%s.png" % theme))
        win.app.show_inbox()
        # The pinned tab takes its checked look from an idle callback;
        # the frame must not be grabbed before it has run.
        win.app.sync_tab_accent()
        snap(off, os.path.join(out, "ideabox-%s.png" % theme))
        Gtk.main_quit()
        return False

    Gtk.main = lambda: (GLib.timeout_add(700, render), real_main())[1]
    try:
        jd.start_gui(use_statusicon=True)
    finally:
        Gtk.main = real_main


def dialog(name, end_marker, out, width, height, filename, extra=None):
    """Build one of the dialogs defined inside start_gui and render it."""
    body = re.search(r"\n    class %s\(Gtk\.Dialog\):\n(.*?)\n\n    class %s"
                     % (name, end_marker), SRC, re.S).group(1)
    body = textwrap.dedent(body)
    ns = {"Gtk": Gtk, "Gdk": Gdk, "GLib": GLib, "_": jd._, "VERSION": jd.VERSION,
          "SETTINGS_SCHEMA": jd.SETTINGS_SCHEMA, "CONFIG_PATH": jd.CONFIG_PATH,
          "available_languages": jd.available_languages, "INBOX": jd.INBOX,
          "read_update_cache": jd.read_update_cache, "Pango": None,
          "newer_version": jd.newer_version, "open_in_editor": lambda p: None,
          "attach_image_paste": lambda tv: None, "subprocess": jd.subprocess,
          "add_headerbar": lambda d, t: None,
          "mark_body": lambda d: d.get_content_area().get_style_context()
          .add_class("jd-body")}
    ns.update(extra or {})
    exec("class %s(Gtk.Dialog):\n%s" % (name, textwrap.indent(body, "    ")), ns)
    dlg = ns[name](*ns["_args"])
    dlg.show_all()
    for _ in range(3):
        while Gtk.events_pending():
            Gtk.main_iteration()
    content = dlg.get_content_area()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    content.get_parent().remove(content)
    box.pack_start(content, True, True, 0)
    styled(box, width, height, os.path.join(out, filename))


def main():
    # One palette per process: start_gui installs the stylesheet once, and the
    # dialogs are drawn against whatever it left in place. Re-running ourselves
    # is simpler than teaching the app to switch mid-flight for a screenshot.
    theme = os.environ.get("CCDO_SHOT_THEME")
    if not theme:
        for choice in ("dark", "light"):
            subprocess.run([sys.executable, os.path.abspath(__file__), OUTDIR],
                           env=dict(os.environ, CCDO_SHOT_THEME=choice),
                           check=True)
        return

    if theme == "light":
        jd.prefers_dark = lambda *a, **k: False

    os.makedirs(OUTDIR, exist_ok=True)
    cfg = seed()
    jd.load_language("en")
    print("Rendering %s into %s" % (theme, os.path.relpath(OUTDIR, ROOT)))
    note_window(OUTDIR, theme)
    dialog("SettingsDialog", "QuickNoteDialog", OUTDIR, 560, 780,
           "settings-window-%s.png" % theme, extra={"_args": (None, cfg)})
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
