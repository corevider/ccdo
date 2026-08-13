#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ccdo — a note / task queue that lives in the system tray.

It opens a tab per live Claude Code session; a note goes to whichever session
you wrote it under. The point is to park a new task without interrupting the
work in progress, then hand it over when the current one finishes.

Usage:
    ccdo                        # start the tray daemon
    ccdo add "text" [--target api:0.0] [--project api]
    ccdo show | toggle          # show/hide the window (for a hotkey)
    ccdo list [target]          # list pending tasks
    ccdo peek | next            # print the next one (next marks it 'sent')
    ccdo done <id> | delete <id>
    ccdo history [n]            # what left the queue (completed + deleted)
    ccdo log [n] [target]       # delivery decisions: what went, what didn't, why
    ccdo send [id]              # hand over to Claude Code
    ccdo sessions               # live sessions with their color and label
    ccdo targets                # raw tmux pane list
    ccdo paste-check            # macOS: what the clipboard holds, and can we save it
    ccdo path                   # where the files live
    ccdo version [--check]      # version; --check asks whether a newer one is out
    ccdo update [--apply]       # print the update command, or run it
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import traceback
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from datetime import datetime

APP_NAME = "ccdo"
VERSION = "1.0.24"

# The desktop half (tray, window, notifications) is Linux; the queue, the
# hooks and the tmux delivery run anywhere Unix. Rather than sprinkle
# sys.platform checks around, the handful of places that shell out to a
# desktop tool branch on these.
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt"
REPO = "corevider/ccdo"
DEBUG = bool(os.environ.get("CCDO_DEBUG"))

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")), APP_NAME)
DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local", "share")), APP_NAME)
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()

CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
STORE_PATH = os.path.join(DATA_DIR, "queue.json")
LOCK_PATH = os.path.join(DATA_DIR, ".queue.lock")
QUEUE_MD = os.path.join(DATA_DIR, "QUEUE.md")
HISTORY_PATH = os.path.join(DATA_DIR, "history.jsonl")
HISTORY_LOCK = os.path.join(DATA_DIR, ".history.lock")
HISTORY_MD = os.path.join(DATA_DIR, "HISTORY.md")
DROPS_DIR = os.path.join(DATA_DIR, "drops")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
ICON_DIR = os.path.join(DATA_DIR, "icons")
SOCK_PATH = os.path.join(RUNTIME_DIR, "ccdo.sock")
SESSIONS_PATH = os.path.join(DATA_DIR, "sessions.json")
SESSIONS_LOCK = os.path.join(DATA_DIR, ".sessions.lock")
AUTO_PATH = os.path.join(DATA_DIR, "auto.json")
UPDATE_PATH = os.path.join(DATA_DIR, "update.json")
AUTO_LOCK = os.path.join(DATA_DIR, ".auto.lock")
EVENTS_PATH = os.path.join(DATA_DIR, "events.jsonl")
EVENTS_LOCK = os.path.join(DATA_DIR, ".events.lock")
EVENTS_KEEP = 2000               # gunluk bu satir sayisina kirpilir
CLAUDE_SETTINGS = os.path.join(HOME, ".claude", "settings.json")

INBOX = "__inbox__"          # hedefi olmayan notlarin sanal bolumu
HISTORY_UI_LIMIT = 50        # newest records shown in the history section

DEFAULT_CONFIG = {
    "delivery": "auto",              # auto | tmux | xdotool | file
    "inline_max_chars": 8000,        # longer text is dropped into a file
    "auto_enter": True,
    "enter_delay": 0.25,
    "send_prefix": "",
    "file_ref_template": "Read {path} and do the task in it.",
    "xdotool_window": "claude",
    "notify": True,
    "discover_interval": 4,          # tmux scan interval (s)
    "process_match": ["claude"],     # command looked for in a pane process tree
    "pane_match": ["claude"],         # text match used when ps is unavailable
    "auto_advance": False,           # may the Stop hook empty the queue by itself
    "max_auto_advance": 3,           # tasks in a row per user message
    "session_stale_after": 43200,    # a record silent this long counts as dead
    "skip_advance_on_question": True,  # hold back if Claude ended with a question
    "question_patterns": [],         # extra question patterns (regex)
    "check_updates": True,           # look for a newer release once a day
    "screenshot_paste_seconds": 120,  # paste a just-taken screenshot file; 0 = off
    "screenshot_dir": "",            # where those land; empty = ask the desktop
    "language": "auto",              # auto = the desktop language; en, tr, ...
    "use_claude_session_name": True, # take the tab name from Claude Code
    "use_claude_theme_color": True,  # take the color from the Claude Code theme
    "use_claude_agent_color": True,  # take the color from /color
    "window_keep_above": True,       # keep the window on top
    "window_utility_hint": False,    # UTILITY hint (troublesome on some WMs)
    "sessions": {
        # The key is either a full target ("proj:0.0") or a session name.
        # "proj": { "label": "My Project", "color": "#7fc98f",
        #           "queue_file": "~/dev/proj/QUEUE.md" }
    },
}

# --------------------------------------------------------------------------- #
#  Tema
# --------------------------------------------------------------------------- #

# Colors are not written rule by rule; every surface feeds from this table.
# Both palettes carry the same keys, so the CSS stays a single template.
THEME_DARK = {
    "bg": "#131417",            # pencere zemini
    "surface": "#191b1f",       # kart
    "sunken": "#0d0e11",        # girdi: karttan bir ton koyu, sinirlari belli
    "raised": "#212429",        # buton, uzerine binen yuzey
    "raised_hi": "#282c32",     # hover
    "border": "#2b2f36",
    "border_soft": "#212429",
    "text": "#e9eaee",
    "dim": "#9aa1ac",
    "faint": "#697079",
    "accent": "#d97757",        # Claude's terracotta, for surfaces with no
    "accent_hi": "#e28b6e",     # session color of their own
    "accent_ink": "#141518",
    "accent_wash": "rgba(217, 119, 87, 0.14)",
    "warn": "#d8b46a",
    "warn_bg": "rgba(216, 180, 106, 0.08)",
    "warn_edge": "rgba(216, 180, 106, 0.22)",
    "mono": "monospace",
    "r_lg": "9px",              # kart / girdi
    "r_md": "7px",              # buton
}

THEME_LIGHT = {
    "bg": "#f4f5f7",
    "surface": "#ffffff",
    "sunken": "#eceef2",
    "raised": "#eceef1",
    "raised_hi": "#e1e4e9",
    "border": "#d2d7de",
    "border_soft": "#e4e7ec",
    "text": "#1b1d21",
    "dim": "#5b616b",
    "faint": "#868c96",
    "accent": "#b2543a",
    "accent_hi": "#96432c",
    "accent_ink": "#ffffff",
    "accent_wash": "rgba(178, 84, 58, 0.12)",
    "warn": "#8a6410",
    "warn_bg": "rgba(138, 100, 16, 0.08)",
    "warn_edge": "rgba(138, 100, 16, 0.28)",
    "mono": "monospace",
    "r_lg": "9px",
    "r_md": "7px",
}


# --------------------------------------------------------------------------- #
#  Translation
# --------------------------------------------------------------------------- #

# Source strings are English. A catalog is a flat JSON file mapping the source
# string to its translation, so adding a language means dropping one file in —
# no build step, no gettext toolchain, no extra dependency.
LOCALE_DIRS = (
    os.path.join(DATA_DIR, "locales"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales"),
    "/usr/share/ccdo/locales",
)

_CATALOG = {}
_CATALOG_META = {}
_LANG = "en"


def locale_file(code):
    for d in LOCALE_DIRS:
        path = os.path.join(d, "%s.json" % code)
        if os.path.exists(path):
            return path
    return None


def available_languages():
    """Language codes we ship or the user dropped in, English always first."""
    found = {"en"}
    for d in LOCALE_DIRS:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        found.update(n[:-5] for n in names if n.endswith(".json"))
    return ["en"] + sorted(found - {"en"})


def desktop_language():
    """Language code the desktop asks for, e.g. tr_TR.UTF-8 -> tr."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = (os.environ.get(var) or "").strip()
        if val and val not in ("C", "POSIX"):
            return re.split(r"[._@]", val)[0].split("-")[0].lower()
    return "en"


def load_language(code=None):
    """Load a catalog. 'auto' (or None) follows the desktop language.

    A missing or broken catalog is not an error: untranslated strings fall
    back to their English source, which is always readable.
    """
    global _CATALOG, _CATALOG_META, _LANG
    if not code or code == "auto":
        code = desktop_language()
    _CATALOG, _CATALOG_META, _LANG = {}, {}, "en"
    if code == "en":
        return _LANG
    path = locale_file(code)
    if not path:
        return _LANG
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            meta = data.get("__meta__")
            _CATALOG_META = meta if isinstance(meta, dict) else {}
            _CATALOG = {k: v for k, v in data.items()
                        if k != "__meta__" and isinstance(v, str) and v}
            _LANG = code
    except Exception as e:
        sys.stderr.write("ccdo: could not read %s (%s)\n" % (path, e))
    return _LANG


def _(text):
    """Translate a source string; unknown strings pass through unchanged."""
    return _CATALOG.get(text, text)


def language_question_patterns():
    """Question patterns the active language contributes, if any."""
    pats = _CATALOG_META.get("question_patterns")
    return [p for p in pats if isinstance(p, str)] if isinstance(pats, list) else []


# --------------------------------------------------------------------------- #
#  Version and updates
# --------------------------------------------------------------------------- #

UPDATE_URL = "https://api.github.com/repos/%s/releases/latest" % REPO
RELEASES_URL = "https://github.com/%s/releases/latest" % REPO
UPDATE_INTERVAL = 86400          # ayni gun icinde tekrar sorma


def parse_version(text):
    """'v1.2.3' -> (1, 2, 3). A part that will not compare counts as 0."""
    nums = re.findall(r"\d+", (text or "").strip())
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def newer_version(latest, current=VERSION):
    """Is `latest` newer than `current`? Empty or malformed means no."""
    return bool(latest) and parse_version(latest) > parse_version(current)


def read_update_cache():
    try:
        with open(UPDATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def check_update(cfg=None, force=False, timeout=6):
    """Find out the newest version; cache the answer.

    We reach the network once a day: asking on every start is both wasteful
    and ties the working directory to a network delay. Failure is silent —
    checking for updates must never get in the way of the actual work.
    """
    if cfg is not None and not cfg.get("check_updates", True):
        return {}
    cache = read_update_cache()
    if not force:
        try:
            if time.time() - float(cache.get("checked_at", 0)) < UPDATE_INTERVAL:
                return cache
        except (TypeError, ValueError):
            pass
    try:
        req = urllib.request.Request(
            UPDATE_URL, headers={"Accept": "application/vnd.github+json",
                                 "User-Agent": "ccdo/%s" % VERSION})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        latest = (data.get("tag_name") or "").strip()
        notes = (data.get("body") or "").strip()
    except Exception as e:
        if DEBUG:
            sys.stderr.write("[ccdo] guncelleme bakilamadi: %s\n" % e)
        cache["checked_at"] = time.time()
    else:
        # The notes are cached with the tag so the window can show them
        # without a second round trip — and without the network at all if the
        # user opens the dialog later.
        cache = {"checked_at": time.time(), "latest": latest, "notes": notes}
    try:
        ensure_dirs()
        atomic_write(UPDATE_PATH, json.dumps(cache, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return cache


def plain_markdown(text):
    """Flatten release-note markdown for a plain TextView.

    The notes come from GitHub as markdown; showing the raw markers turns a
    short list into visual noise, and pulling in a renderer for four kinds of
    marker would be a poor trade.
    """
    out = []
    for line in (text or "").splitlines():
        line = re.sub(r"^(#+)\s*(.+)$", lambda m: m.group(2).upper(), line)
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        line = re.sub(r"^\s*[-*]\s+", "  • ", line)
        if line.strip() in ("```", "```bash", "```sh"):
            continue
        out.append(line)
    return "\n".join(out).strip()


def update_command(ref=None):
    """The line that installs `ref` — by default the release we just saw.

    Pinning it matters: the window says "v1.2.3 is out", and installing main
    could hand over something else entirely.
    """
    if ref is None:
        ref = read_update_cache().get("latest", "")
    prefix = "CCDO_REF=%s " % ref if ref else ""
    return ("curl -fsSL https://raw.githubusercontent.com/%s/main/install.sh"
            " | %sbash" % (REPO, prefix))


def prefers_dark(settings=None):
    """Does the desktop ask for a dark theme?

    GNOME's color-scheme first, then GTK's prefer-dark flag, then the theme
    name. None of them is enough alone: on Yaru, color-scheme can say
    'prefer-dark' while gtk-application-prefer-dark-theme stays False.
    """
    if IS_MAC:
        # macOS sets this key only while dark is on; missing means light.
        rc, out, __ = run_cmd(["defaults", "read", "-g", "AppleInterfaceStyle"])
        return rc == 0 and "dark" in out.lower()

    rc, out, __ = run_cmd(["gsettings", "get",
                          "org.gnome.desktop.interface", "color-scheme"])
    if rc == 0:
        val = out.strip().strip("'\"")
        if val == "prefer-dark":
            return True
        if val == "prefer-light":
            return False
    if settings is not None:
        try:
            if settings.get_property("gtk-application-prefer-dark-theme"):
                return True
            name = (settings.get_property("gtk-theme-name") or "").lower()
            return name.endswith("-dark") or "dark" in name
        except Exception:
            pass
    return True


def active_theme(settings=None):
    return THEME_DARK if prefers_dark(settings) else THEME_LIGHT


PALETTE = [
    "#e0a458", "#5ea9e0", "#7fc98f", "#d17c9a",
    "#a58ee0", "#e07a5f", "#6fc9c0", "#c9b458",
]

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">
  <g fill="none" stroke="#d8d8d8" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
    <path d="M4.5 3.2h10.2l3.1 3.1v12.5H4.5z"/>
    <path d="M14.7 3.2v3.1h3.1"/>
    <path d="M7.4 10h7.2M7.4 13.2h7.2M7.4 16.4h4.3"/>
  </g>
</svg>
"""


def draw_icon_png(path, size=22, color=(0.85, 0.85, 0.85)):
    """Draw the icon with Cairo and save it as PNG.

    The icon ships as SVG, but GdkPixbuf only reads SVG where librsvg is
    installed — and on macOS it usually is not, which left the status item
    holding an image it could not load: an invisible, clickable gap in the
    menu bar. Cairo is always there, so we draw the same shape instead of
    rasterising anything.
    """
    import cairo

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    k = size / 22.0
    cr.scale(k, k)
    cr.set_source_rgb(*color)
    cr.set_line_width(1.6)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)

    # The page, with its corner folded over.
    cr.move_to(4.5, 3.2)
    cr.line_to(14.7, 3.2)
    cr.line_to(17.8, 6.3)
    cr.line_to(17.8, 18.8)
    cr.line_to(4.5, 18.8)
    cr.close_path()
    cr.stroke()
    cr.move_to(14.7, 3.2)
    cr.line_to(14.7, 6.3)
    cr.line_to(17.8, 6.3)
    cr.stroke()

    # Three lines of writing, the last one short.
    for y, x2 in ((10.0, 14.6), (13.2, 14.6), (16.4, 11.7)):
        cr.move_to(7.4, y)
        cr.line_to(x2, y)
    cr.stroke()

    surface.write_to_png(path)
    return path


def svg_supported():
    """Can GdkPixbuf read SVG here? (librsvg is optional and often absent.)"""
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        return any(f.get_name() == "svg" for f in GdkPixbuf.Pixbuf.get_formats())
    except Exception:
        return False


def write_icons(prefer_png=False):
    """Put the icon on disk and return the file the tray should use.

    prefer_png is for callers that do not go through GdkPixbuf: NSImage only
    learned to read SVG in macOS 13, and a bitmap is what a menu bar template
    image wants anyway.
    """
    ensure_dirs()
    svg_path = os.path.join(ICON_DIR, "ccdo.svg")
    png_path = os.path.join(ICON_DIR, "ccdo.png")
    if not os.path.exists(svg_path):
        atomic_write(svg_path, ICON_SVG)
    try:
        if not os.path.exists(png_path):
            draw_icon_png(png_path)
    except Exception as e:
        sys.stderr.write("ccdo: could not draw the icon (%s)\n" % e)
        return svg_path
    if prefer_png:
        return png_path
    return svg_path if svg_supported() else png_path


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def ensure_dirs():
    for d in (CONFIG_DIR, DATA_DIR, DROPS_DIR, IMAGES_DIR, ICON_DIR):
        os.makedirs(d, exist_ok=True)


def atomic_write(path, text):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def new_image_path(when=None):
    """A fresh path for a pasted image, timestamped so the folder reads well."""
    ensure_dirs()
    stamp = (when or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return os.path.join(IMAGES_DIR, "%s-%s.png" % (stamp, uuid.uuid4().hex[:6]))


def save_pasted_image(pixbuf, when=None):
    """Write a pasted image to disk as PNG and return its path.

    Claude Code reads an image path that appears in the prompt, so putting the
    path into the note is enough: the queue, the history and the drop files
    all stay plain text.
    """
    path = new_image_path(when)
    pixbuf.savev(path, "png", [], [])
    return path


def quote_path(path):
    """A path as it should read in a prompt: quoted, so a space cannot split it."""
    return '"%s"' % path.replace('"', '\\"')


def image_insert_text(paths, at_line_start):
    """What an attached file becomes in the note: its path, on a line of its own.

    Quoted, because names with spaces are the rule rather than the exception —
    a macOS screenshot is called "Screen Shot 2026-08-13 at 17.20.45.png" —
    and an unquoted path would be read as several words.
    """
    lines = "\n".join(quote_path(p) for p in paths)
    return ("" if at_line_start else "\n") + lines + "\n"


def file_paths_from_uris(uris):
    """Pick the existing files out of a list of file:// URIs.

    Any file, not only images: Claude Code opens the path it is given, so a
    PDF or a log dropped into a note is worth as much as a screenshot.
    """
    out = []
    for uri in uris or []:
        if not uri.startswith("file://"):
            continue
        path = urllib.parse.unquote(urllib.parse.urlparse(uri).path)
        if os.path.isfile(path):
            out.append(path)
    return out


def screenshot_dir(cfg=None):
    """Where the desktop drops a screenshot file."""
    told = os.path.expanduser((cfg or {}).get("screenshot_dir") or "")
    if told:
        return told
    if IS_MAC:
        rc, out, __ = run_cmd(["defaults", "read", "com.apple.screencapture",
                               "location"])
        if rc == 0 and out.strip():
            path = os.path.expanduser(out.strip())
            if os.path.isdir(path):
                return path
        return os.path.join(HOME, "Desktop")
    pictures = os.environ.get("XDG_PICTURES_DIR") or os.path.join(HOME, "Pictures")
    shots = os.path.join(pictures, "Screenshots")
    return shots if os.path.isdir(shots) else pictures


def recent_screenshot(within=120, folder=None, now=None):
    """The newest screenshot taken in the last `within` seconds, if any.

    Command+Shift+4 writes a file and leaves the clipboard alone — only the
    Control variant copies — so pasting straight after taking one finds an
    empty clipboard. Rather than explain that, we go and look for the file.

    The window is what keeps this from being a surprise: only a shot taken
    moments ago counts, so a paste never reaches for something you have
    forgotten about.
    """
    if within <= 0:
        return None
    folder = folder or screenshot_dir()
    now = now if now is not None else time.time()
    best, best_age = None, None
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in names:
        if name.startswith(".") or not name.lower().endswith(IMAGE_SUFFIXES):
            continue
        path = os.path.join(folder, name)
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        # A negative age is a clock that disagrees with the filesystem, not a
        # file from the future; a small tolerance keeps those usable.
        if age > within or age < -5:
            continue
        if best_age is None or age < best_age:
            best, best_age = path, age
    return best


class FileLock:
    def __init__(self, path):
        self.path = path
        self.fh = None

    def __enter__(self):
        import fcntl
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fh = open(self.path, "a+")
        fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        import fcntl
        try:
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
            self.fh = None
        return False


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def text_glyph(ch):
    """Ask for the text presentation of a glyph (U+FE0E).

    Characters like ❓ and ⭐ also have an emoji presentation, and fontconfig
    hands them to the color emoji font — which broke the single-color icon
    set in the window.
    """
    return ch + "︎"


def notify(title, body, cfg=None):
    """A desktop notification, where the desktop offers one."""
    if cfg is not None and not cfg.get("notify", True):
        return
    if IS_MAC:
        script = ('display notification %s with title %s'
                  % (applescript_string(body), applescript_string(title)))
        args = ["osascript", "-e", script]
    else:
        args = ["notify-send", "-a", APP_NAME, "-i", "accessories-text-editor",
                title, body]
    if not shutil.which(args[0]):
        return
    try:
        subprocess.run(args, check=False, timeout=5)
    except Exception:
        pass


def applescript_string(text):
    """Quote a string for osascript. AppleScript escapes with backslashes."""
    return '"%s"' % (text or "").replace("\\", "\\\\").replace('"', '\\"')


GUI_EDITORS = ("gnome-text-editor", "gedit", "kate", "mousepad", "xed",
               "pluma", "code", "subl")


def open_in_editor(path):
    """Open a file in a text editor.

    xdg-open goes by the extension, and .json is bound to the browser on most
    desktops: the settings file opened in Firefox instead of an editor. We try
    the default application for text/plain first, then the editors we know of,
    and only fall back to xdg-open.
    """
    if IS_MAC:
        # -t hands the file to the default *text* editor rather than whatever
        # claims the extension, which is the same problem xdg-open has.
        try:
            subprocess.Popen(["open", "-t", path])
            return True
        except OSError:
            pass

    if shutil.which("gtk-launch"):
        rc, out, __ = run_cmd(["xdg-mime", "query", "default", "text/plain"])
        desktop = out.strip() if rc == 0 else ""
        if desktop and run_cmd(["gtk-launch", desktop, path], timeout=15)[0] == 0:
            return True

    for exe in GUI_EDITORS:
        if shutil.which(exe):
            try:
                subprocess.Popen([exe, path])
                return True
            except OSError:
                continue

    try:
        subprocess.Popen(["xdg-open", path])
        return True
    except OSError:
        sys.stderr.write("ccdo: could not open %s\n" % path)
        return False


def run_cmd(args, timeout=10):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "command not found: %s" % args[0]
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"


def slug(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower()) or "x"


def hex_to_rgba(hexcolor, alpha):
    h = (hexcolor or "#888888").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        r = g = b = 136
    return "rgba(%d,%d,%d,%.2f)" % (r, g, b, alpha)


def ink_for(hexcolor):
    """The text color that stays readable on this background.

    The send button takes its background from the session color, and the
    palette holds both dark and light tones. Fixed dark text disappeared on a
    dark session color such as red. The threshold leans white: unless the
    background is clearly light, white wins.
    """
    h = (hexcolor or "#888888").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return "#ffffff"
    return "#141518" if (0.299 * r + 0.587 * g + 0.114 * b) > 190 else "#ffffff"


# --------------------------------------------------------------------------- #
#  Config
# --------------------------------------------------------------------------- #

def load_config():
    ensure_dirs()
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                user = json.load(f)
            if isinstance(user, dict):
                cfg.update(user)
        except Exception as e:
            sys.stderr.write("could not read the config (%s), using defaults\n" % e)
    else:
        atomic_write(CONFIG_PATH, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    return cfg


def save_config(cfg):
    atomic_write(CONFIG_PATH, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


# The settings window is generated from this table. Keeping it the single
# source stops the window from falling behind when a setting is added, and the
# test checks every key here really exists in DEFAULT_CONFIG.
# (key, kind, label, description, ...kind-specific)
SETTINGS_SCHEMA = (
    ("Auto-advance", (
        ("auto_advance", "bool", "Auto is on by default",
         "A per-directory preference (auto.json) overrides this."),
        ("max_auto_advance", "int", "Most tasks in a row",
         "With auto on, how many tasks may be handed over before you type "
         "again. Your message resets the counter.", 1, 50),
        ("skip_advance_on_question", "bool", "Hold back when Claude asks",
         "If a turn ends with a question, delivery locks — a task must not "
         "stand in for your answer."),
    )),
    ("Delivery", (
        ("auto_enter", "bool", "Press Enter after typing the text",
         "When off the note is typed into the prompt but not submitted."),
        ("enter_delay", "float", "Wait between text and Enter (s)",
         "Gives slow terminals time to finish the paste.", 0.0, 3.0),
        ("inline_max_chars", "int", "Notes longer than this go to a file",
         "Shorter notes are pasted straight into the prompt.", 200, 100000),
        ("send_prefix", "str", "Prefix added to every delivery",
         "e.g. \"[ccdo] \" — may be left empty."),
        ("delivery", "choice", "Route for notes with no target",
         "Sending from the inbox; auto tries tmux, xdotool and file in turn.",
         ("auto", "tmux", "xdotool", "file")),
    )),
    ("Sessions", (
        ("discover_interval", "int", "tmux scan interval (s)",
         "For panes without hooks. With hooks installed there is no scan.",
         1, 60),
        ("use_claude_session_name", "bool", "Take the tab name from Claude Code",
         "The name given by /rename or --name."),
        ("use_claude_agent_color", "bool", "Take the color from /color",
         "If you ran /color in the session, the tab uses that color."),
        ("use_claude_theme_color", "bool", "Take the color from the Claude Code theme",
         "The theme's claude accent, for sessions on a custom theme."),
    )),
    ("Window and notifications", (
        ("window_keep_above", "bool", "Keep the window on top", ""),
        ("notify", "bool", "Desktop notifications", ""),
        ("language", "lang", "Language",
         "auto follows the desktop. Drop a JSON catalog into "
         "~/.local/share/ccdo/locales to add one."),
    )),
)


def session_override(cfg, target):
    """Look up config.sessions by full target first, then by session name."""
    table = cfg.get("sessions") or {}
    if target in table:
        return table[target] or {}
    sess = (target or "").split(":", 1)[0]
    return table.get(sess) or {}


def auto_color(key):
    return PALETTE[zlib.crc32((key or "").encode("utf-8")) % len(PALETTE)]


# --------------------------------------------------------------------------- #
#  Session registry (filled in by the Claude Code hooks)
# --------------------------------------------------------------------------- #

class Registry:
    """Session facts straight from the Claude Code hooks.

    The tmux scan was a guess; this registry comes from Claude Code itself:
    session_id, cwd, pane ID and the current state (busy/idle/waiting).
    """

    STATES = ("busy", "idle", "waiting", "ended")

    def _read(self):
        if not os.path.exists(SESSIONS_PATH):
            return {"version": 1, "sessions": {}}
        try:
            with open(SESSIONS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("sessions", {})
            return data
        except Exception:
            return {"version": 1, "sessions": {}}

    def _write(self, data):
        atomic_write(SESSIONS_PATH, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def all(self):
        with FileLock(SESSIONS_LOCK):
            return self._read()["sessions"]

    def get(self, session_id):
        return self.all().get(session_id)

    def upsert(self, session_id, **fields):
        if not session_id:
            return None
        with FileLock(SESSIONS_LOCK):
            data = self._read()
            rec = data["sessions"].setdefault(session_id, {
                "session_id": session_id,
                "state": "idle",
                "auto_advance": None,
                "advance_count": 0,
            })
            rec.update(fields)
            rec["last_seen"] = now_iso()
            self._write(data)
            return rec

    def drop(self, session_id):
        with FileLock(SESSIONS_LOCK):
            data = self._read()
            if data["sessions"].pop(session_id, None) is not None:
                self._write(data)
                return True
        return False

    def prune(self, max_age):
        """Drop records left behind by a Claude Code process that crashed."""
        cutoff = time.time() - max_age
        with FileLock(SESSIONS_LOCK):
            data = self._read()
            keep = {}
            changed = False
            for sid, rec in data["sessions"].items():
                if rec.get("state") == "ended":
                    changed = True
                    continue
                ts = rec.get("last_seen")
                try:
                    age_ok = datetime.fromisoformat(ts).timestamp() >= cutoff
                except Exception:
                    age_ok = True
                if age_ok:
                    keep[sid] = rec
                else:
                    changed = True
            if changed:
                data["sessions"] = keep
                self._write(data)
        return True

    def by_target(self, target):
        for rec in self.all().values():
            if rec.get("target") == target:
                return rec
        return None


class AutoPrefs:
    """The 'auto' preference, kept per working directory.

    It used to be stored per session_id, and every Claude restart minted a new
    session_id — so the switch quietly turned itself off while the user still
    believed auto was on. Tied to the directory, every new session in the same
    project inherits it.
    """

    def _key(self, cwd):
        if not cwd:
            return None
        try:
            return os.path.realpath(cwd.rstrip("/")) or None
        except Exception:
            return None

    def _read(self):
        try:
            with open(AUTO_PATH, encoding="utf-8") as f:
                return json.load(f).get("dirs") or {}
        except Exception:
            return {}

    def get(self, cwd):
        """The remembered preference for a directory, or None if never set.

        A session opened in a subdirectory belongs to the same project, so it
        inherits the parent's preference; the longest matching path wins, and
        a preference set on a subdirectory is not overridden by the one above.
        """
        key = self._key(cwd)
        if not key:
            return None
        best = None
        for path, val in self._read().items():
            if key == path or key.startswith(path.rstrip(os.sep) + os.sep):
                if best is None or len(path) > len(best[0]):
                    best = (path, val)
        return None if best is None else bool(best[1])

    def set(self, cwd, value):
        key = self._key(cwd)
        if not key:
            return
        with FileLock(AUTO_LOCK):
            dirs = self._read()
            dirs[key] = bool(value)
            atomic_write(AUTO_PATH, json.dumps({"version": 1, "dirs": dirs},
                                               indent=2, ensure_ascii=False) + "\n")


SID_PREFIX = "sid:"


def resolve_pane_target(session_id=None):
    """Produce a stable target key for a session.

    Inside tmux, $TMUX_PANE gives a permanent pane ID and we can type into the
    terminal. Outside tmux we cannot reach the terminal, but the hooks still
    let us identify the session: a virtual "sid:<session_id>" target is used
    and delivery goes through the Stop hook.
    """
    pane = os.environ.get("TMUX_PANE", "").strip()
    if pane:
        return pane
    if session_id:
        return SID_PREFIX + session_id
    return None


def is_tmux_target(target):
    return bool(target) and not str(target).startswith(SID_PREFIX)


def session_target_for_cwd(cfg, cwd=None):
    """Find the registered session whose directory contains this one.

    The /next slash command runs inside a Claude Code session, so its working
    directory matches that session's — which keeps the command from pulling a
    task out of some other session's queue by accident.
    """
    try:
        here = os.path.realpath(cwd or os.getcwd())
    except Exception:
        return None
    best = None
    for rec in Registry().all().values():
        rc = rec.get("cwd")
        if not rc or not rec.get("target"):
            continue
        rc = os.path.realpath(rc.rstrip("/"))
        if here == rc or here.startswith(rc + os.sep):
            if best is None or len(rc) > len(best[0]):
                best = (rc, rec["target"])
    return best[1] if best else None


ANSI16 = {
    "black": "#000000", "red": "#cd3131", "green": "#0dbc79", "yellow": "#e5e510",
    "blue": "#2472c8", "magenta": "#bc3fbc", "cyan": "#11a8cd", "white": "#e5e5e5",
    "blackbright": "#666666", "redbright": "#f14c4c", "greenbright": "#23d18b",
    "yellowbright": "#f5f543", "bluebright": "#3b8eea", "magentabright": "#d670d6",
    "cyanbright": "#29b8db", "whitebright": "#ffffff",
}


def ansi256_to_hex(n):
    """Convert an xterm 256-color index to hex."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    if 0 <= n <= 15:
        order = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
                 "blackbright", "redbright", "greenbright", "yellowbright",
                 "bluebright", "magentabright", "cyanbright", "whitebright"]
        return ANSI16[order[n]]
    if 16 <= n <= 231:
        n -= 16
        steps = [0, 95, 135, 175, 215, 255]
        r, g, b = steps[n // 36], steps[(n // 6) % 6], steps[n % 6]
        return "#%02x%02x%02x" % (r, g, b)
    if 232 <= n <= 255:
        v = 8 + (n - 232) * 10
        return "#%02x%02x%02x" % (v, v, v)
    return None


def parse_theme_color(value):
    """Convert a Claude Code theme color value to hex.

    Accepted forms: #rrggbb, #rgb, rgb(r,g,b), ansi256(n), ansi:<name>.
    """
    if not isinstance(value, str):
        return None
    v = value.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", v)
    if m:
        return "#" + m.group(1).lower()
    m = re.fullmatch(r"#([0-9a-fA-F]{3})", v)
    if m:
        return "#" + "".join(c * 2 for c in m.group(1).lower())
    m = re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", v)
    if m:
        try:
            r, g, b = (min(255, max(0, int(x))) for x in m.groups())
            return "#%02x%02x%02x" % (r, g, b)
        except ValueError:
            return None
    m = re.fullmatch(r"ansi256\(\s*(\d+)\s*\)", v)
    if m:
        return ansi256_to_hex(m.group(1))
    m = re.fullmatch(r"ansi:(\w+)", v)
    if m:
        return ANSI16.get(m.group(1).lower())
    return None


# The session color set with /color in Claude Code. The name list is not
# visible from outside, so we map the known ones; an unrecognised name falls
# back to the older route (theme > palette).
AGENT_COLORS = {
    "red": "#cd3131", "green": "#0dbc79", "yellow": "#e5e510",
    "blue": "#2472c8", "magenta": "#bc3fbc", "cyan": "#11a8cd",
    "white": "#e5e5e5", "black": "#666666",
    "orange": "#d18616", "purple": "#a56ec4", "pink": "#e06c9f",
    "teal": "#1f9e9e", "gray": "#8a8f99", "grey": "#8a8f99",
}


def parse_agent_color(value):
    """Convert a /color value to hex — it may be a name or a color literal."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in AGENT_COLORS:
        return AGENT_COLORS[v]
    return parse_theme_color(v)


_AGENT_COLOR_CACHE = {}      # path -> (file stamp, color)
_AGENT_COLOR_SEEN = {}       # path -> the last colour we saw
_AGENT_COLOR_SCANNED = set() # bastan sona bir kez taranmis dosyalar


def _scan_agent_color(f):
    """Scan forward through an open file and return the last agent-color."""
    found = None
    for raw in f:
        if b"agent-color" not in raw:
            continue
        try:
            obj = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("type") == "agent-color":
            got = parse_agent_color(obj.get("agentColor"))
            if got:
                found = got          # en sonuncusu kazanir
    return found


def transcript_agent_color(path, max_bytes=262144):
    """Read the color a session set with /color out of its transcript.

    Claude Code rewrites this entry at the end of the file throughout the
    session, so reading the tail is normally enough. Two guards:

    - If the tail has none and the file is large, we scan from the start ONCE;
      the color may have been set long ago and never written since.
    - If nothing is found, the last known color is kept. A color is not
      something you "undo", and losing a tab's color just because the entry
      scrolled out of the tail window would be wrong.
    """
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None

    key = (st.st_mtime, st.st_size)
    hit = _AGENT_COLOR_CACHE.get(path)
    if hit and hit[0] == key:
        return hit[1]

    found = None
    try:
        with open(path, "rb") as f:
            if st.st_size > max_bytes:
                f.seek(st.st_size - max_bytes)
                f.readline()          # yarim satiri at
            found = _scan_agent_color(f)

        if found is None and st.st_size > max_bytes \
                and path not in _AGENT_COLOR_SCANNED:
            _AGENT_COLOR_SCANNED.add(path)
            with open(path, "rb") as f:
                found = _scan_agent_color(f)
    except OSError:
        return None

    if found is None:
        found = _AGENT_COLOR_SEEN.get(path)
    else:
        _AGENT_COLOR_SEEN[path] = found

    _AGENT_COLOR_CACHE[path] = (key, found)
    return found


def _read_json(path):
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def claude_theme_preference(cwd):
    """Find the theme a session is actually using.

    Claude Code settings are layered: project-local, project, then user. A
    theme can be set per project, so every project may pick its own.
    """
    candidates = []
    if cwd:
        d = os.path.realpath(cwd)
        # Walk upwards to find the project root
        while True:
            candidates.append(os.path.join(d, ".claude", "settings.local.json"))
            candidates.append(os.path.join(d, ".claude", "settings.json"))
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    candidates.append(os.path.join(HOME, ".claude", "settings.json"))

    for path in candidates:
        data = _read_json(path)
        if isinstance(data, dict):
            theme = data.get("theme")
            if isinstance(theme, str) and theme.strip():
                return theme.strip()
    return None


def claude_theme_color(cwd, tokens=("claude", "promptBorder", "planMode")):
    """Take the accent color from the session's Claude Code theme.

    Only CUSTOM themes yield a color: with the built-ins (dark, light, …)
    every session would land on the same one, defeating the point of telling
    sessions apart.
    """
    pref = claude_theme_preference(cwd)
    if not pref or not pref.startswith("custom:"):
        return None
    slug = pref.split(":", 1)[1].strip()
    if not slug:
        return None
    data = _read_json(os.path.join(HOME, ".claude", "themes", slug + ".json"))
    if not isinstance(data, dict):
        return None
    overrides = data.get("overrides")
    if not isinstance(overrides, dict):
        return None
    for token in tokens:
        color = parse_theme_color(overrides.get(token))
        if color:
            return color
    return None



_TITLE_CACHE = {}

# The session name is not kept in a file of its own: it is written into the
# transcript .jsonl as an entry. /rename and --name produce "custom-title",
# the generated one "ai-title"; a name the user gave always wins.
TITLE_TYPES = {
    "custom-title": 3, "custom_title": 3, "customTitle": 3,
    "agent-name": 2, "agent_name": 2, "agentName": 2,
    "ai-title": 1, "ai_title": 1, "aiTitle": 1, "summary": 1,
}
TITLE_FIELDS = ("name", "title", "customTitle", "aiTitle", "sessionTitle", "text")


def _extract_title(obj):
    """Extract (priority, title) from a transcript line, or None."""
    if not isinstance(obj, dict):
        return None
    rank = TITLE_TYPES.get(str(obj.get("type", "")))
    if rank is None:
        # Shapes with no type field that still carry a title
        for key, r in (("customTitle", 3), ("aiTitle", 1), ("sessionTitle", 3)):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return r, val.strip()
        return None
    for field in TITLE_FIELDS:
        val = obj.get(field)
        if isinstance(val, str) and val.strip():
            return rank, val.strip()
        if isinstance(val, dict):
            inner = val.get("title") or val.get("name")
            if isinstance(inner, str) and inner.strip():
                return rank, inner.strip()
    return None


def transcript_title(path, max_bytes=262144):
    """Read the session name out of the transcript.

    A bounded chunk of the file's tail is read; the highest-priority, most
    recently written title wins. The result is cached against the file stamp.
    """
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_mtime, st.st_size)
    hit = _TITLE_CACHE.get(path)
    if hit and hit[0] == key:
        return hit[1]

    best = None
    try:
        with open(path, "rb") as f:
            if st.st_size > max_bytes:
                f.seek(st.st_size - max_bytes)
                f.readline()          # yarim satiri at
            for idx, raw in enumerate(f):
                try:
                    obj = json.loads(raw.decode("utf-8", "replace"))
                except Exception:
                    continue
                got = _extract_title(obj)
                if got and (best is None or got[0] >= best[0]):
                    best = (got[0], got[1], idx)
    except OSError:
        return None

    title = best[1] if best else None
    if title and len(title) > 60:
        title = title[:59] + "…"
    _TITLE_CACHE[path] = (key, title)
    if DEBUG and title:
        sys.stderr.write("[ccdo] transcript title: %r (priority %s)\n"
                         % (title, best[0]))
    return title


def pick_color(cfg, target, label, cwd, transcript=None):
    """Pick a session color; returns (color, is_fixed, source).

    Priority: config.sessions[...].color  >  /color  >  a custom Claude Code
    theme  >  the palette. The first three count as an explicit choice and the
    collision resolver leaves them alone.

    /color outranks the theme color: a theme belongs to the project, while
    /color was chosen deliberately for that one session.
    """
    ov = session_override(cfg, target)
    if ov.get("color"):
        return ov["color"], True, "config"
    if cfg.get("use_claude_agent_color", True):
        agent = transcript_agent_color(transcript)
        if agent:
            return agent, True, "/color"
    if cfg.get("use_claude_theme_color", True):
        themed = claude_theme_color(cwd)
        if themed:
            pref = claude_theme_preference(cwd) or ""
            return themed, True, pref.split(":", 1)[-1] or "tema"
    return auto_color(ov.get("label") or label), False, "palet"


def registry_sessions(cfg):
    """Turn registry records into the shape discover_sessions returns."""
    reg = Registry()
    reg.prune(int(cfg.get("session_stale_after", 900)))
    out, explicit = [], set()
    for rec in reg.all().values():
        target = rec.get("target")
        if not target:
            continue
        ov = session_override(cfg, target)
        cwd = rec.get("cwd") or ""
        live_title = None
        if cfg.get("use_claude_session_name", True):
            live_title = transcript_title(rec.get("transcript")) or rec.get("title")
        label = (ov.get("label") or live_title or rec.get("label")
                 or (os.path.basename(cwd.rstrip("/")) if cwd else None)
                 or target)
        color, fixed, csrc = pick_color(cfg, target, label, cwd, rec.get("transcript"))
        if fixed:
            explicit.add(target)
        out.append({
            "target": target,
            "label": label,
            "color": color,
            "color_source": csrc,
            "cwd": cwd,
            "cmd": "claude",
            "queue_file": ov.get("queue_file"),
            "live": rec.get("state") != "ended",
            "state": rec.get("state", "idle"),
            "session_id": rec.get("session_id"),
            "auto_advance": rec.get("auto_advance"),
            "source": "hook",
        })
    out.sort(key=lambda s: s["target"])
    return out, explicit


# --------------------------------------------------------------------------- #
#  Session discovery
# --------------------------------------------------------------------------- #

def tmux_panes():
    """A list of (target, command, cwd, title, pane_pid, pane_id)."""
    if not shutil.which("tmux"):
        return []
    fmt = ("#{session_name}:#{window_index}.#{pane_index}\t#{pane_current_command}"
           "\t#{pane_current_path}\t#{pane_title}\t#{pane_pid}\t#{pane_id}")
    rc, out, __ = run_cmd(["tmux", "list-panes", "-a", "-F", fmt])
    if rc != 0:
        return []
    panes = []
    for line in out.splitlines():
        parts = line.split("\t")
        while len(parts) < 6:
            parts.append("")
        panes.append(tuple(parts[:6]))
    return panes


def process_tree():
    """ppid -> [(pid, args)] and pid -> args. (None, None) if ps is missing."""
    rc, out, __ = run_cmd(["ps", "-eo", "pid=,ppid=,args="])
    if rc != 0 or not out.strip():
        return None, None
    children, args_of = {}, {}
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        args_of[pid] = parts[2]
        children.setdefault(ppid, []).append((pid, parts[2]))
    return children, args_of


def pane_process_match(children, args_of, pane_pid, needles):
    """Does the pane itself, or one of its children, match any needle?"""
    try:
        root = int(pane_pid)
    except (TypeError, ValueError):
        return False
    seen, stack = set(), [root]
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        low = (args_of.get(p) or "").lower()
        if any(n in low for n in needles):
            return True
        for pid, cmdline in children.get(p, []):
            if any(n in cmdline.lower() for n in needles):
                return True
            stack.append(pid)
    return False


_COLOR_CACHE = {}


def dedupe_colors(sessions, explicit):
    """Give clashing sessions a free palette color, leaving overrides alone.

    The assignment is kept in _COLOR_CACHE: once a session has a color it
    keeps it even if the list order changes. Otherwise colors would shift on
    every scan and the window would rebuild itself constantly.
    """
    used = set()
    pending = []
    for s in sessions:
        if s["target"] in explicit:
            # An explicit choice (config or the Claude Code theme) is kept as
            # is and never cached — editing the theme file updates the color
            # on the next scan.
            used.add(s["color"])
            _COLOR_CACHE.pop(s["target"], None)
        elif s["target"] in _COLOR_CACHE:
            s["color"] = _COLOR_CACHE[s["target"]]
            used.add(s["color"])
        else:
            pending.append(s)

    for s in pending:
        color = s["color"]
        if color in used:
            color = next((c for c in PALETTE if c not in used), color)
        s["color"] = color
        _COLOR_CACHE[s["target"]] = color
        used.add(color)
    return sessions


def discover_sessions(cfg):
    """Find live Claude Code sessions and give each a label and a color.

    The registry comes first: with the Claude Code hooks installed its facts
    are exact (session_id, pane ID, current state). For panes without hooks
    the older tmux scan takes over, looking for 'claude' in the pane's process
    tree — that way node processes like vite or a game server are not counted
    as sessions.
    """
    out, explicit = registry_sessions(cfg)
    known = {s["target"] for s in out}

    def norm(p):
        p = (p or "").rstrip("/")
        try:
            return os.path.realpath(p) if p else ""
        except Exception:
            return p

    known_cwds = {norm(s["cwd"]) for s in out if s.get("cwd")}

    proc_needles = [m.lower() for m in (cfg.get("process_match") or ["claude"])]
    text_needles = [m.lower() for m in (cfg.get("pane_match") or ["claude"])]
    children, args_of = process_tree()

    for target, cmd, cwd, title, pane_pid, pane_id in tmux_panes():
        # Keep one pane from showing up twice, once as "%12" (from the hook
        # registry) and once as "proj:0.0" (from the scan). Match on the pane
        # ID first: that one is exact.
        if target in known or (pane_id and pane_id in known):
            continue
        if children is not None:
            hit = pane_process_match(children, args_of, pane_pid, proc_needles)
        else:
            hit = any(n in " ".join((cmd, title)).lower() for n in text_needles)
        if not hit:
            continue
        if cwd and norm(cwd) in known_cwds:
            continue
        ov = session_override(cfg, target)
        name = target.split(":", 1)[0]
        label = (ov.get("label")
                 or (title if title and title.lower() != cmd.lower() else None)
                 or (os.path.basename(cwd.rstrip("/")) if cwd else None)
                 or name)
        color, fixed, csrc = pick_color(cfg, target, label, cwd)
        if fixed:
            explicit.add(target)
        out.append({
            "target": target,
            "label": label,
            "color": color,
            "color_source": csrc,
            "cwd": cwd,
            "cmd": cmd,
            "queue_file": ov.get("queue_file"),
            "live": True,
            "state": "unknown",
            "session_id": None,
            "auto_advance": None,
            "source": "scan",
        })
    out.sort(key=lambda s: s["target"])
    return dedupe_colors(out, explicit)


def ghost_session(cfg, target):
    """A target that is no longer live but still holds tasks."""
    ov = session_override(cfg, target)
    name = (target or "").split(":", 1)[0]
    return {
        "target": target,
        "label": ov.get("label") or name or "?",
        "color": ov.get("color") or auto_color(ov.get("label") or name),
        "cwd": "", "cmd": "", "queue_file": ov.get("queue_file"),
        "color_source": "palet",
        "live": False,
    }


def session_folder(sess):
    """The last part of the session working directory: the folder name."""
    return os.path.basename((sess.get("cwd") or "").rstrip("/"))


def session_line(sess):
    """The line under the title: folder name, target, and the color source.

    Once the session name arrives from Claude Code it takes over the header
    and the folder name disappeared; keeping the folder here shows both. If
    the name already equals the folder we do not repeat it.
    """
    parts = []
    folder = session_folder(sess)
    if folder and folder != sess.get("label"):
        parts.append(folder)
    target = sess.get("target") or ""
    if target:
        parts.append(target if sess.get("live") else "%s · " % target + _("closed"))
    csrc = sess.get("color_source")
    if csrc and csrc not in ("palet", "config"):
        parts.append("tema: %s" % csrc)
    return "  ·  ".join(parts)


# One source of truth for session state: the mark on the tab and the words in
# the page header come from this table, so they cannot drift apart.
STATE_MARKS = {
    "busy":    (text_glyph("●"), "running", "media-record-symbolic"),
    "idle":    (text_glyph("✓"), "idle", "emblem-ok-symbolic"),
    "waiting": (text_glyph("⚠"), "waiting on a prompt", "dialog-warning-symbolic"),
    "asking":  (text_glyph("❓"), "asked a question", "dialog-question-symbolic"),
    "ended":   (text_glyph("·"), "ended", "window-close-symbolic"),
}


def state_icon(sess):
    """The tab's state icon; it comes from the same table as mark and words."""
    if not sess.get("live", True):
        return STATE_MARKS["ended"][2]
    row = STATE_MARKS.get(sess.get("state") or "")
    return row[2] if row else ""


def state_mark(sess):
    """The state mark shown left of the name on a tab."""
    if not sess.get("live", True):
        return STATE_MARKS["ended"][0]
    return STATE_MARKS.get(sess.get("state") or "", ("", "", ""))[0]


def state_word(sess):
    """Just the state in words, for when the mark sits in its own widget."""
    if not sess.get("live", True):
        return _(STATE_MARKS["ended"][1])
    return _(STATE_MARKS.get(sess.get("state") or "", ("", "", ""))[1])


def state_text(sess):
    """The '<mark> <state>' line shown in the page header."""
    if not sess.get("live", True):
        row = STATE_MARKS["ended"]
        return "%s %s" % (row[0], _(row[1]))
    row = STATE_MARKS.get(sess.get("state") or "")
    return "%s %s" % (row[0], _(row[1])) if row else ""


def scroll_step(direction, dx=0.0, dy=0.0):
    """Turn a scroll event into a tab step: +1 forward, -1 back, 0 ignore.

    direction: "up" | "down" | "left" | "right" | "smooth". Modern mice mostly
    send "smooth", carrying the direction in the deltas; a mouse with a
    horizontal wheel may fill in dx instead.
    """
    if direction in ("down", "right"):
        return 1
    if direction in ("up", "left"):
        return -1
    if direction == "smooth":
        delta = dy if dy else dx
        if delta > 0:
            return 1
        if delta < 0:
            return -1
    return 0


def session_tab_text(sess, width=14):
    """The short name shown on a tab."""
    name = sess.get("label") or sess.get("target") or "?"
    return name if len(name) <= width else name[:width - 1] + "…"


def session_tooltip(sess):
    """Tab tooltip: session name, folder and target together."""
    parts = [sess.get("label") or "?"]
    folder = session_folder(sess)
    if folder and folder != sess.get("label"):
        parts.append(folder)
    if sess.get("target"):
        parts.append(sess["target"])
    return " — ".join(parts)


# --------------------------------------------------------------------------- #
#  History
# --------------------------------------------------------------------------- #
#
# Tasks that left the queue (completed and deleted) are written here. Before,
# completed ones piled up in queue.json forever and deleted ones vanished
# without a trace; there was no way to look back at what you had done.
#
# Format: one JSON record per line, append-only. It does NOT share the queue
# lock — FileLock is not reentrant, and taking it twice in the same process
# deadlocks. So a history write always happens AFTER the queue lock is
# released.


def append_history(event, task, ts=None):
    """Append a task that left the queue to the history.

    `ts` is when the event actually happened: stamping "now" while migrating
    tasks left over from an older version would misrepresent the timeline, so
    the caller may pass the task's own stamp.

    If the history cannot be written the queue operation still counts as
    successful: keeping records must not block the work itself.
    """
    rec = {"ts": ts or now_iso(), "event": event, "task": task}
    try:
        with FileLock(HISTORY_LOCK):
            with open(HISTORY_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        return False
    export_history_markdown()
    return True


# The decision log. It exists to answer one question: "why didn't this task
# go?" The wording lives in one place so the log, the notification and the
# warning in the window cannot drift apart.
EVENT_TEXT = {
    "advance": _("auto: task handed over (%(used)s/%(cap)s)"),
    "sent": _("sent: %(detail)s"),
    "fail": _("could not send: %(detail)s"),
    "skip_question": _("auto skipped: Claude asked a question (%(detail)s)"),
    "skip_budget": _("auto stopped: budget spent (%(used)s/%(cap)s)"
                   " — it resumes once you type"),
    "skip_auto_off": _("auto is off: ccdo hands over nothing on its own"),
}


def describe_event(rec):
    """Render a log record in plain words."""
    kind = rec.get("kind", "")
    tpl = EVENT_TEXT.get(kind)
    if not tpl:
        return kind
    fields = {"used": "?", "cap": "?", "via": "?", "detail": ""}
    fields.update({k: v for k, v in rec.items() if v is not None})
    try:
        return tpl % fields
    except Exception:
        return kind


def log_event(kind, target=None, task=None, **fields):
    """Record a decision. A decision repeated back to back is written once.

    Squashing repeats is essential: a reason like 'auto is off' is reborn at
    the end of every turn, and writing them all would bury the events that
    matter under noise.
    """
    rec = {"ts": now_iso(), "kind": kind, "target": target,
           "task_id": (task or {}).get("id"),
           "task_text": ((task or {}).get("text") or "").splitlines()[0][:70] or None}
    rec.update(fields)
    try:
        with FileLock(EVENTS_LOCK):
            last = None
            if os.path.exists(EVENTS_PATH):
                try:
                    with open(EVENTS_PATH, "rb") as f:
                        tail = f.read()[-4096:].decode("utf-8", "replace")
                    lines = [l for l in tail.splitlines() if l.strip()]
                    last = json.loads(lines[-1]) if lines else None
                except Exception:
                    last = None
            if last and all(last.get(k) == rec.get(k)
                            for k in ("kind", "target", "task_id", "detail")):
                return False
            with open(EVENTS_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            _trim_events()
    except OSError:
        return False
    return True


def _trim_events():
    """Keep the log from growing forever; only the last EVENTS_KEEP lines."""
    try:
        if os.path.getsize(EVENTS_PATH) < 512 * 1024:
            return
        with open(EVENTS_PATH, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= EVENTS_KEEP:
            return
        atomic_write(EVENTS_PATH, "".join(lines[-EVENTS_KEEP:]))
    except OSError:
        pass


BLOCK_KINDS = ("skip_budget", "skip_question", "skip_auto_off", "fail")


def last_block_reason(target):
    """The target's last decision, in words, if it was one that blocked delivery.

    We read backwards: a successful delivery in between voids the reason, or
    the window would keep showing an obstacle that has already cleared.
    """
    for rec in reversed(read_events(limit=40, target=target)):
        kind = rec.get("kind")
        if kind in ("advance", "sent"):
            return None
        if kind in BLOCK_KINDS:
            return describe_event(rec)
    return None


def read_events(limit=None, target=None):
    """Return log records oldest first; malformed lines are skipped."""
    out = []
    try:
        with open(EVENTS_PATH, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if target and rec.get("target") != target:
                    continue
                out.append(rec)
    except OSError:
        return []
    return out[-limit:] if limit else out


_HISTORY_CACHE = {}


def read_history(limit=None):
    """Return history records oldest first; malformed lines are skipped.

    The window calls this on every refresh, so the parsed list is reused for
    as long as the file stamp is unchanged.
    """
    try:
        st = os.stat(HISTORY_PATH)
    except OSError:
        return []

    key = (st.st_mtime, st.st_size)
    hit = _HISTORY_CACHE.get(HISTORY_PATH)
    if hit and hit[0] == key:
        out = hit[1]
    else:
        out = []
        try:
            with open(HISTORY_PATH, encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and isinstance(rec.get("task"), dict):
                        out.append(rec)
        except OSError:
            return []
        _HISTORY_CACHE[HISTORY_PATH] = (key, out)
    return list(out[-limit:]) if limit else list(out)


def history_for_target(key, limit=None):
    """One session's history (or the inbox's), newest first.

    Same mapping as the queue list: untargeted tasks belong to the inbox.
    """
    out = [rec for rec in read_history()
           if ((key == INBOX and not (rec["task"].get("target")))
               or rec["task"].get("target") == key)]
    out.reverse()
    return out[:limit] if limit else out


EVENT_GLYPH = {"done": text_glyph("✓"), "deleted": text_glyph("✕")}


def export_history_markdown(limit=300):
    """Produce a readable HISTORY.md — newest first, grouped by day."""
    recs = read_history()
    total = len(recs)
    recs = list(reversed(recs))[:limit]

    lines = ["# " + _("Task history"), "", "_%s · ccdo_" % now_iso(), ""]
    if not recs:
        lines.append(_("No records yet."))
    else:
        if total > limit:
            lines.append(_("_Showing the latest %d of %d records — all of "
                           "them are in `history.jsonl`._") % (limit, total))
            lines.append("")
        day = None
        for rec in recs:
            ts = rec.get("ts") or ""
            if ts[:10] != day:
                day = ts[:10]
                lines.append("## %s" % (day or "?"))
                lines.append("")
            t = rec["task"]
            first = (t.get("text") or "").strip().splitlines()
            first = first[0] if first else ""
            lines.append("- %s `%s` %s  <sub>%s · %s</sub>" % (
                EVENT_GLYPH.get(rec.get("event"), "·"), t.get("id", "?"), first,
                ts[11:19], t.get("target") or t.get("project") or "ideabox"))
        lines.append("")
    try:
        atomic_write(HISTORY_MD, "\n".join(lines).rstrip() + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
#  Store
# --------------------------------------------------------------------------- #

class Store:
    def __init__(self, cfg):
        self.cfg = cfg

    def _read(self):
        if not os.path.exists(STORE_PATH):
            return {"version": 2, "tasks": []}
        try:
            with open(STORE_PATH, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("tasks", [])
            return data
        except Exception:
            try:
                shutil.copy2(STORE_PATH, STORE_PATH + ".corrupt-%d" % int(time.time()))
            except Exception:
                pass
            return {"version": 2, "tasks": []}

    def _write(self, data):
        atomic_write(STORE_PATH, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        self._export_markdown(data)

    def fingerprint(self):
        """Tell from the content whether the file really changed.

        Watching mtime was misleading: the filesystem or an atomic write can
        move the stamp while the content stays identical, and the window kept
        refreshing for nothing.
        """
        try:
            with open(STORE_PATH, "rb") as f:
                data = f.read()
        except OSError:
            return ("", 0)
        return (zlib.crc32(data), len(data))

    def all(self):
        with FileLock(LOCK_PATH):
            return self._read()["tasks"]

    def pending(self, target=None):
        ts = [t for t in self.all() if t.get("status") == "pending"]
        if target is None:
            return ts
        if target == INBOX:
            return [t for t in ts if not t.get("target")]
        return [t for t in ts if t.get("target") == target]

    def add(self, text, target=None, project=None, priority=0):
        text = (text or "").strip()
        if not text:
            return None
        task = {
            "id": uuid.uuid4().hex[:8],
            "text": text,
            "target": target or None,
            "project": project or (target.split(":", 1)[0] if target else "ideabox"),
            "status": "pending",
            "priority": int(priority),
            "created_at": now_iso(),
            "sent_at": None,
        }
        with FileLock(LOCK_PATH):
            data = self._read()
            data["tasks"].append(task)
            self._write(data)
        return task

    def update(self, task_id, **fields):
        """Update a task. Marking it 'done' moves it from the queue to history."""
        found = archived = None
        with FileLock(LOCK_PATH):
            data = self._read()
            for t in data["tasks"]:
                if t["id"] == task_id:
                    t.update(fields)
                    found = t
                    break
            if found is None:
                return None
            if found.get("status") == "done":
                archived = found
                data["tasks"] = [x for x in data["tasks"] if x["id"] != task_id]
            self._write(data)
        if archived is not None:
            append_history("done", archived)
        return found

    def delete(self, task_id):
        removed = None
        with FileLock(LOCK_PATH):
            data = self._read()
            for t in data["tasks"]:
                if t["id"] == task_id:
                    removed = t
                    break
            if removed is None:
                return False
            data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
            self._write(data)
        append_history("deleted", removed)
        return True

    def purge_done(self):
        """Move 'done' tasks still sitting in the queue into the history.

        Before the history existed, completed tasks piled up in queue.json;
        this carries them out without losing any. Returns how many moved.
        """
        with FileLock(LOCK_PATH):
            data = self._read()
            moved = [t for t in data["tasks"] if t.get("status") == "done"]
            if moved:
                data["tasks"] = [t for t in data["tasks"]
                                 if t.get("status") != "done"]
                self._write(data)
        for t in moved:
            # These were completed long ago; stamping them with the moment of
            # the move would misrepresent the timeline.
            append_history("done", t, ts=t.get("sent_at") or t.get("created_at"))
        return len(moved)

    def reorder(self, task_id, delta):
        """Swap a task with its neighbour under the SAME target.

        Shifting by +-1 in the global list was wrong: with another session's
        task in between, the click looked like it did nothing.
        """
        with FileLock(LOCK_PATH):
            data = self._read()
            tasks = data["tasks"]
            idx = next((i for i, t in enumerate(tasks) if t["id"] == task_id), None)
            if idx is None:
                return False
            target = tasks[idx].get("target")
            # Global indices of unfinished tasks sharing this target
            peers = [i for i, t in enumerate(tasks)
                     if t.get("target") == target and t.get("status") != "done"]
            pos = peers.index(idx)
            new_pos = pos + (1 if delta > 0 else -1)
            if new_pos < 0 or new_pos >= len(peers):
                return False
            j = peers[new_pos]
            tasks[idx], tasks[j] = tasks[j], tasks[idx]
            self._write(data)
            return True

    def next_pending(self, target=None):
        """The next task is the FIRST task in the queue.

        It used to be sorted by the star, which quietly broke the order the
        user had arranged by hand. The queue order is now the only source of
        truth; the star is a visual mark and nothing more.
        """
        p = self.pending(target)
        return p[0] if p else None

    def active_targets(self):
        return sorted({t.get("target") for t in self.all()
                       if t.get("status") in ("pending", "sent") and t.get("target")})

    def _export_markdown(self, data):
        groups = {}
        for t in data["tasks"]:
            if t.get("status") == "done":
                continue
            groups.setdefault(t.get("target") or _("(unassigned)"), []).append(t)

        def render(subset):
            lines = ["# " + _("Task queue"), "", "_%s · ccdo_" % now_iso(), ""]
            if not subset:
                lines.append(_("No pending tasks."))
            for key in sorted(subset):
                lines.append("## %s" % key)
                lines.append("")
                for t in subset[key]:
                    mark = "x" if t.get("status") == "sent" else " "
                    star = " ★" if int(t.get("priority", 0)) > 0 else ""
                    first, __, rest = t["text"].strip().partition("\n")
                    lines.append("- [%s] `%s`%s %s" % (mark, t["id"], star, first))
                    for ln in rest.splitlines():
                        lines.append("      %s" % ln)
                lines.append("")
            return "\n".join(lines).rstrip() + "\n"

        try:
            atomic_write(QUEUE_MD, render(groups))
        except Exception:
            pass

        for key, meta in (self.cfg.get("sessions") or {}).items():
            path = (meta or {}).get("queue_file")
            if not path:
                continue
            subset = {k: v for k, v in groups.items()
                      if k == key or k.split(":", 1)[0] == key}
            try:
                atomic_write(os.path.expanduser(path), render(subset))
            except Exception:
                pass


# --------------------------------------------------------------------------- #
#  Delivery
# --------------------------------------------------------------------------- #

def prepare_payload(cfg, task):
    """Build the text handed to Claude for a task.

    The text goes over directly: being multi-line is not on its own a reason
    to drop it into a file, because tmux can paste it in one piece. Files are
    for very long text only; putting one in the way of a short note cost
    Claude an extra read.
    """
    text = task["text"].strip()
    prefix = cfg.get("send_prefix", "") or ""
    if len(text) <= int(cfg.get("inline_max_chars", 8000)):
        return (prefix + text), None
    return payload_via_file(cfg, task)


def payload_via_file(cfg, task):
    """Write the task text to a drop file and return a line pointing at it."""
    text = task["text"].strip()
    prefix = cfg.get("send_prefix", "") or ""
    ensure_dirs()
    name = re.sub(r"[^a-z0-9]+", "-", text.lower())[:40].strip("-") or "task"
    path = os.path.join(DROPS_DIR, "%s-%s.md" % (task["id"], name))
    header = _("# Task %s\n\n- Target: %s\n- Created: %s\n\n---\n\n") % (
        task["id"], task.get("target") or _("(unassigned)"), task.get("created_at", ""))
    atomic_write(path, header + text + "\n")
    line = _(cfg.get("file_ref_template", "Read {path} and do the task in it."))
    return (prefix + line.format(path=path)), path


def tmux_type(target, payload):
    """Type text into a pane's prompt.

    Multi-line text goes as a bracketed paste (`paste-buffer -p -r`): it
    reaches the pane between ESC[200~ and ESC[201~ with raw newlines, which is
    indistinguishable from a real paste. `-r` is required — without it tmux
    turns newlines into carriage returns and Claude submits halfway through.
    """
    if "\n" not in payload:
        rc, __, err = run_cmd(["tmux", "send-keys", "-t", target, "-l", payload])
        return rc == 0, (err.strip() or _("tmux send-keys failed"))

    buf = "ccdo-%d" % os.getpid()
    rc, __, err = run_cmd(["tmux", "set-buffer", "-b", buf, "--", payload])
    if rc != 0:
        return False, err.strip() or _("tmux set-buffer failed")
    rc, __, err = run_cmd(["tmux", "paste-buffer", "-b", buf, "-d", "-p", "-r",
                          "-t", target])
    if rc != 0:
        run_cmd(["tmux", "delete-buffer", "-b", buf])
        return False, err.strip() or _("tmux paste-buffer failed")
    return True, ""


def send_tmux(cfg, target, payload):
    if not target:
        return False, _("no target")
    ok, err = tmux_type(target, payload)
    if not ok:
        return False, err
    if cfg.get("auto_enter", True):
        time.sleep(float(cfg.get("enter_delay", 0.25)))
        rc, __, err = run_cmd(["tmux", "send-keys", "-t", target, "Enter"])
        if rc != 0:
            return False, err.strip() or _("could not send Enter")
    return True, "→ %s" % target


def send_xdotool(cfg, payload):
    if not shutil.which("xdotool"):
        return False, _("xdotool is not installed")
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return False, _("xdotool does not work on Wayland")
    rc, out, __ = run_cmd(["xdotool", "search", "--name", cfg.get("xdotool_window", "claude")])
    wins = [w for w in out.split() if w.strip()]
    if not wins:
        return False, _("window not found")
    win = wins[-1]
    run_cmd(["xdotool", "windowactivate", "--sync", win])
    time.sleep(0.15)
    rc, __, err = run_cmd(["xdotool", "type", "--window", win, "--delay", "12", payload], timeout=60)
    if rc != 0:
        return False, err.strip() or _("xdotool type failed")
    if cfg.get("auto_enter", True):
        time.sleep(float(cfg.get("enter_delay", 0.25)))
        run_cmd(["xdotool", "key", "--window", win, "Return"])
    return True, "xdotool → %s" % win


def deliver(cfg, store, task, force=False):
    """Deliver a task and record the outcome.

    Logging happens at one point: marking each of _deliver's exits separately
    was easy to forget the moment a new branch appeared.
    """
    ok, msg = _deliver(cfg, store, task, force=force)
    log_event("sent" if ok else "fail", target=task.get("target"), task=task,
              detail=msg)
    return ok, msg


def _deliver(cfg, store, task, force=False):
    target = task.get("target")

    # A session outside tmux: we cannot type into the terminal, but the Stop
    # hook can hand the task over. Mark it and let the hook deliver it.
    if target and not is_tmux_target(target):
        rec = Registry().by_target(target) or {}
        if rec.get("state") == "ended":
            return False, _("session ended")
        if rec.get("state") == "asking" and not force:
            return False, (_("Claude asked a question — answer it first. "
                           "Use --force to send anyway"))
        if rec.get("state") == "waiting" and not force:
            return False, _("session is waiting on a permission prompt — answer it, then send")
        auto = rec.get("auto_advance")
        if auto is None:
            auto = bool(cfg.get("auto_advance", False))
        store.update(task["id"], push=False)
        if auto and rec.get("state") == "busy":
            return True, _("queued — auto is on, Claude takes it when the turn ends")
        if auto:
            return True, (_("auto is on but Claude is idle; a turn has to end first. "
                          "For it right now, type /next in the session"))
        return False, (_("cannot type into this session (not in tmux). "
                       "Type /next in it, or switch 'auto' on in the tab"))

    payload, drop_path = prepare_payload(cfg, task)

    if target:
        live = {s["target"] for s in discover_sessions(cfg)}
        rec = Registry().by_target(target)
        if rec:
            if rec.get("state") == "asking" and not force:
                return False, (_("Claude asked a question — sending would answer it "
                               "on your behalf. Use --force if you mean to"))
            if rec.get("state") == "waiting" and not force:
                return False, _("session is waiting on a permission prompt — answer it, then send")
            if rec.get("state") == "ended":
                return False, _("session ended: %s") % target
        elif target not in live:
            rc, __, __ = run_cmd(["tmux", "has-session", "-t", target.split(":", 1)[0]])
            if rc != 0:
                return False, _("session is closed: %s") % target
        ok, msg = send_tmux(cfg, target, payload)
        if not ok and drop_path is None and "\n" in payload:
            # The bracketed paste did not take (an old tmux, a truncated
            # buffer): drop the text into a file and try again with the
            # one-line reference.
            payload, drop_path = payload_via_file(cfg, task)
            ok, msg = send_tmux(cfg, target, payload)
        if ok:
            store.update(task["id"], status="sent", sent_at=now_iso(),
                         drop_path=drop_path, delivered_via="tmux")
        return ok, msg

    # A note with no target (inbox): tmux if there is exactly one candidate,
    # otherwise xdotool or the file
    order = {"tmux": ["tmux"], "xdotool": ["xdotool"], "file": ["file"]}.get(
        cfg.get("delivery", "auto"), ["tmux", "xdotool", "file"])
    last = ""
    for m in order:
        if m == "tmux":
            sessions = discover_sessions(cfg)
            if len(sessions) != 1:
                last = _("no target assigned (%d candidate sessions)") % len(sessions)
                continue
            ok, msg = send_tmux(cfg, sessions[0]["target"], payload)
        elif m == "xdotool":
            ok, msg = send_xdotool(cfg, payload)
        else:
            ok, msg = True, _("written to the queue file")
        if ok:
            store.update(task["id"], status="sent", sent_at=now_iso(),
                         drop_path=drop_path, delivered_via=m)
            return True, msg
        last = msg
    return False, last or _("could not deliver")


# --------------------------------------------------------------------------- #
#  Claude Code hook'lari
# --------------------------------------------------------------------------- #

HOOK_EVENTS = ("SessionStart", "SessionEnd", "UserPromptSubmit", "Notification", "Stop")


def hook_session_start(cfg, store, reg, data):
    sid = data.get("session_id")
    target = resolve_pane_target(sid)
    cwd = data.get("cwd") or ""
    tp = data.get("transcript_path") or ""
    # session_title: the name given by /rename or --name (an official field)
    title = (data.get("session_title") or "").strip() or None
    fields = dict(target=target, cwd=cwd, state="idle", transcript=tp, title=title,
                  label=os.path.basename(cwd.rstrip("/")) or None)
    # A new session means a new session_id; the 'auto' preference is inherited
    # from the directory, or the switch quietly turned itself off every time
    # Claude restarted.
    remembered = AutoPrefs().get(cwd)
    if remembered is not None:
        fields["auto_advance"] = remembered
    reg.upsert(sid, **fields)
    ipc_send("rediscover")

    pending = [t for t in store.pending() if t.get("target") == target] if target else []
    if not pending:
        return {}
    lines = "; ".join(t["text"].splitlines()[0][:60] for t in pending[:5])
    return {"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": (
            _("The ccdo queue has %d task(s) waiting for this session: %s. "
              "If the user wants one, `ccdo next` hands over the next.")
            % (len(pending), lines))}}


def hook_session_end(cfg, store, reg, data):
    reg.upsert(data.get("session_id"), state="ended")
    ipc_send("rediscover")
    return {}


def hook_user_prompt(cfg, store, reg, data):
    # If the user typed, the turn is not ours: the auto-advance counter
    # resets. It also means any pending question was answered, so the lock
    # lifts.
    reg.upsert(data.get("session_id"), state="busy", advance_count=0,
               transcript=data.get("transcript_path") or None)
    ipc_send("refresh")
    return {}


def hook_notification(cfg, store, reg, data):
    kind = (data.get("notification_type") or data.get("matcher") or "").strip()
    msg = (data.get("message") or "").lower()
    waiting = ("permission" in kind.lower() or "permission" in msg
               or "idle" in kind.lower() or "needs_input" in kind.lower())
    sid = data.get("session_id")

    # Only the user's answer (UserPromptSubmit) lifts the "asking" lock. The
    # idle notification arrives ~60s after a question; letting it overwrite the
    # state would open the lock by itself, silently.
    if (reg.get(sid) or {}).get("state") == "asking":
        reg.upsert(sid, state="asking")
        return {}

    reg.upsert(sid, state="waiting" if waiting else "busy")
    ipc_send("refresh")
    return {}


def last_assistant_text(path, max_bytes=262144):
    """Return the plain text of the last assistant message in a transcript."""
    if not path:
        return ""
    try:
        st = os.stat(path)
    except OSError:
        return ""
    lines = []
    try:
        with open(path, "rb") as f:
            if st.st_size > max_bytes:
                f.seek(st.st_size - max_bytes)
                f.readline()
            lines = f.readlines()
    except OSError:
        return ""

    for raw in reversed(lines):
        try:
            obj = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") not in ("assistant", "message") and \
           (obj.get("role") or obj.get("message", {}).get("role")) != "assistant":
            continue
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    t = blk.get("text")
                    if isinstance(t, str):
                        parts.append(t)
                elif isinstance(blk, str):
                    parts.append(blk)
            if parts:
                return "\n".join(parts)
    return ""


def _entry_role(obj):
    """The role of the message on a transcript line, or None if it is not one."""
    if not isinstance(obj, dict):
        return None
    msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
    return obj.get("role") or msg.get("role")


def transcript_has_turn_text(path):
    """Has this turn's closing text landed in the transcript yet?

    The condition: an assistant line carrying text must appear AFTER the last
    user/tool_result line. Since tool_results arrive mid-turn, that is what
    tells us the text closing the turn has been written.
    """
    try:
        with open(path, "rb") as f:
            lines = f.readlines()
    except OSError:
        return False

    last_user, last_text = -1, -1
    for i, raw in enumerate(lines):
        try:
            obj = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            continue
        role = _entry_role(obj)
        if role == "user":
            last_user = i
        elif role == "assistant":
            msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
            c = msg.get("content")
            if isinstance(c, str) and c.strip():
                last_text = i
            elif isinstance(c, list) and any(
                    isinstance(b, dict) and b.get("type") == "text"
                    and (b.get("text") or "").strip() for b in c):
                last_text = i
    return last_text > last_user


def final_turn_text(path, timeout=3.0, poll=0.05):
    """The assistant text closing the turn — waiting for it to hit disk.

    The Stop hook can run before Claude Code has written the last assistant
    message to the transcript (measured: ~110 ms). Reading in that window
    shows us the previous turn's text instead of this one's — so a turn that
    ended in a question looks question-free and we inject a task in place of
    the user's answer.

    If the timeout expires we carry on with what we have: a turn that really
    ended without text (a tool call only) has no question in it either.
    """
    if not path:
        return ""
    deadline = time.time() + timeout
    while True:
        if transcript_has_turn_text(path):
            return last_assistant_text(path)
        if time.time() >= deadline:
            if DEBUG:
                sys.stderr.write(
                    "[ccdo] tur metni %.1fs icinde yazilmadi\n" % timeout)
            return last_assistant_text(path)
        time.sleep(poll)


# Handing a task to Claude while its turn ends in a question stands in for the
# user's answer and swallows the question. These patterns catch that case.
# They are English; a locale file adds its own under __meta__.question_patterns,
# so a language can teach ccdo how questions look in it.
QUESTION_PATTERNS = [
    r"(would you like|do you want|want me to|should i|shall i|shall we)",
    r"(which one|which would|let me know|your call|prefer|confirm|proceed\?)",
    r"(next phase|move on to|or should|options?:)",
]


def turn_ends_with_question(text, cfg=None):
    """Does the last assistant message end in a decision or approval question?

    A false positive is cheap (auto-advance skips one turn); a false negative
    is expensive (the user's answer gets swallowed). So we stay on the
    cautious side.
    """
    if not text:
        return False, ""
    # Kod bloklarini cikar: icindeki "?" yanlis eslesme yapmasin
    body = re.sub(r"```.*?```", " ", text, flags=re.S)
    tail = body.strip()[-700:]
    if not tail:
        return False, ""

    if tail.rstrip().endswith("?"):
        return True, "ends with a question mark"

    patterns = list(QUESTION_PATTERNS) + language_question_patterns()
    if cfg:
        patterns += list(cfg.get("question_patterns") or [])
    low = tail.lower()
    for pat in patterns:
        try:
            if re.search(pat, low, re.M):
                return True, "pattern: %s" % pat
        except re.error:
            continue

    # A numbered option list plus a question mark anywhere in the text
    if re.search(r"^\s*(?:\d+[.)]|[-*])\s+\S", tail, re.M) and "?" in tail:
        return True, "option list"
    return False, ""


def hook_stop(cfg, store, reg, data):
    """The turn ended. Mark the session idle; with auto on, hand over the next."""
    sid = data.get("session_id")
    rec = reg.get(sid) or {}
    target = rec.get("target") or resolve_pane_target(sid)
    tpath = data.get("transcript_path") or rec.get("transcript")

    # If the turn ended with a question, handing over a task stands in for the
    # user's answer. In that case we mark the session "asking" and send
    # NOTHING on our own.
    asked, why = (False, "")
    if cfg.get("skip_advance_on_question", True):
        asked, why = turn_ends_with_question(final_turn_text(tpath), cfg)

    reg.upsert(sid, state="asking" if asked else "idle", target=target,
               transcript=tpath)
    ipc_send("refresh")

    # With nothing pending there is no decision to explain, so we check that
    # first rather than filling the log with a meaningless line every turn.
    waiting = store.next_pending(target) if target else None

    if asked:
        if waiting:
            log_event("skip_question", target=target, task=waiting, detail=why)
            notify("ccdo: " + _("waiting"),
                   _("Claude asked a question — auto-advance skipped."), cfg)
        return {}

    if not target or not waiting:
        return {}

    # RULE: this hook only hands over a task while "auto" is on. With it off,
    # ccdo injects NOTHING into the session by itself; the user types /next.
    enabled = rec.get("auto_advance")
    if enabled is None:
        enabled = bool(cfg.get("auto_advance", False))
    if not enabled:
        log_event("skip_auto_off", target=target, task=waiting)
        return {}

    # This counter is the guard against an endless loop: every user message
    # resets it (UserPromptSubmit) and every automatic delivery spends one.
    # We do not look at Claude Code's stop_hook_active flag — it is also set on
    # the Stop that follows a task the hook itself handed over, so watching it
    # cut the chain at the first task and left this budget dead code.
    used = int(rec.get("advance_count", 0))
    cap = int(cfg.get("max_auto_advance", 3))
    if used >= cap:
        log_event("skip_budget", target=target, task=waiting, used=used, cap=cap)
        notify("ccdo: oto durdu",
               _("Budget spent (%d/%d) — it resumes once you type.") % (used, cap),
               cfg)
        ipc_send("refresh")
        return {}

    task = waiting
    payload, drop_path = prepare_payload(cfg, task)
    store.update(task["id"], status="sent", sent_at=now_iso(), push=False,
                 drop_path=drop_path, delivered_via="stop_hook")
    reg.upsert(sid, advance_count=used + 1, state="busy")
    log_event("advance", target=target, task=task, used=used + 1, cap=cap)
    ipc_send("refresh")
    notify("ccdo: " + _("next task handed over"), task["text"].splitlines()[0][:80], cfg)
    return {"decision": "block", "reason": payload}


HOOK_HANDLERS = {
    "SessionStart": hook_session_start,
    "SessionEnd": hook_session_end,
    "UserPromptSubmit": hook_user_prompt,
    "Notification": hook_notification,
    "Stop": hook_stop,
}


def run_hook(cfg, store, event):
    """Read the hook JSON from stdin, handle it, print the decision to stdout.

    On error we exit 0 quietly: a fault in ccdo must never break a Claude Code
    session.
    """
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    handler = HOOK_HANDLERS.get(event)
    if handler is None:
        return 0
    try:
        out = handler(cfg, store, Registry(), data) or {}
    except Exception as e:
        sys.stderr.write("ccdo hook error: %s\n" % e)
        return 0
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


def hook_config(exe):
    """The hooks block written into ~/.claude/settings.json."""
    def entry(event, matcher=None):
        h = {"type": "command", "command": exe, "args": ["hook", event]}
        group = {"hooks": [h]}
        if matcher:
            group["matcher"] = matcher
        return group

    return {
        "SessionStart": [entry("SessionStart")],
        "SessionEnd": [entry("SessionEnd")],
        "UserPromptSubmit": [entry("UserPromptSubmit")],
        "Notification": [entry("Notification",
                               "permission_prompt|idle_prompt|agent_needs_input")],
        "Stop": [entry("Stop")],
    }


def install_hooks(dry_run=False):
    """Add the ccdo hooks to ~/.claude/settings.json, keeping any already there."""
    exe = shutil.which("ccdo") or os.path.abspath(sys.argv[0])
    wanted = hook_config(exe)

    settings = {}
    if os.path.exists(CLAUDE_SETTINGS):
        try:
            with open(CLAUDE_SETTINGS, encoding="utf-8") as f:
                settings = json.load(f)
        except Exception as e:
            sys.stderr.write("could not read settings.json: %s\n" % e)
            return 1
    hooks = settings.setdefault("hooks", {})

    def is_ours(group):
        for h in group.get("hooks", []):
            cmd = str(h.get("command", ""))
            args = h.get("args") or []
            if cmd.endswith("ccdo") or (args and args[0] == "hook"):
                return True
        return False

    added = 0
    for event, groups in wanted.items():
        existing = hooks.setdefault(event, [])
        existing[:] = [g for g in existing if not is_ours(g)]
        existing.extend(groups)
        added += len(groups)

    if dry_run:
        print(json.dumps({"hooks": wanted}, indent=2, ensure_ascii=False))
        return 0

    if os.path.exists(CLAUDE_SETTINGS):
        backup = CLAUDE_SETTINGS + ".ccdo-bak"
        shutil.copy2(CLAUDE_SETTINGS, backup)
        print("backup: %s" % backup)
    atomic_write(CLAUDE_SETTINGS, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    print("wrote %d hook(s) -> %s" % (added, CLAUDE_SETTINGS))
    print("Restart any running Claude Code sessions.")
    print("To check: type /hooks inside a session")
    return 0


# --------------------------------------------------------------------------- #
#  IPC
# --------------------------------------------------------------------------- #

def ipc_send(command, timeout=1.5):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(SOCK_PATH)
        s.sendall(command.encode("utf-8"))
        s.shutdown(socket.SHUT_WR)
        data = s.recv(4096)
        s.close()
        return data.decode("utf-8", "replace")
    except Exception:
        return None


class IPCServer(threading.Thread):
    daemon = True

    def __init__(self, handler):
        super().__init__()
        self.handler = handler

    def run(self):
        try:
            if os.path.exists(SOCK_PATH):
                os.unlink(SOCK_PATH)
        except OSError:
            pass
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(SOCK_PATH)
        os.chmod(SOCK_PATH, 0o600)
        sock.listen(8)
        while True:
            try:
                conn, __ = sock.accept()
            except OSError:
                break
            try:
                data = conn.recv(65536).decode("utf-8", "replace").strip()
                conn.sendall((self.handler(data) or "ok").encode("utf-8"))
            except Exception as e:
                try:
                    conn.sendall(("hata: %s" % e).encode("utf-8"))
                except Exception:
                    pass
            finally:
                conn.close()



# --------------------------------------------------------------------------- #
#  macOS menu bar
# --------------------------------------------------------------------------- #
#
# GTK runs on macOS, but it never looks like it belongs there: foreign
# controls, a deprecated status icon, an icon theme that is not installed.
# This is a native front end over the same core — the queue, the hooks, the
# delivery and the log are all shared, only the surface differs.
#
# It is deliberately smaller than the GTK window. The menu carries what the
# window is for — see what is queued, hand the next one over — and writing
# happens in a note window of its own. Reordering, history and the settings
# window stay on Linux; the files and the CLI cover them.

_MAC_ACTIONS = {}                # menu item tag -> callable
_MAC_TAG = [0]                   # tags are never reused, so a stale menu item
                                 # cannot fire someone else's action
_MAC_WINDOWS = []                # open note windows, held so Python keeps them


def mac_action(fn):
    """Park a callable behind a fresh tag and return the tag."""
    _MAC_TAG[0] += 1
    _MAC_ACTIONS[_MAC_TAG[0]] = fn
    return _MAC_TAG[0]


PNG_FILE_TYPE = 4                # NSBitmapImageFileTypePNG


def png_data_from_image(image):
    """An NSImage as PNG bytes, whatever it was made of."""
    from AppKit import NSBitmapImageRep
    tiff = image.TIFFRepresentation()
    if tiff is None:
        return None
    rep = NSBitmapImageRep.imageRepWithData_(tiff)
    if rep is None:
        return None
    return rep.representationUsingType_properties_(PNG_FILE_TYPE, {})


def files_from_pasteboard(pb):
    """Paths for the files on the pasteboard, whatever kind they are.

    Not only images: a PDF, a log, a spreadsheet dropped into a note is worth
    the same as a screenshot, because Claude Code opens a path it is given.
    The file has to exist — a link copied out of a browser also arrives as a
    URL, and that is not an attachment.
    """
    from Foundation import NSURL

    out = []
    for url in pb.readObjectsForClasses_options_([NSURL], None) or []:
        path = str(url.path() or "")
        if path and os.path.isfile(path):
            out.append(path)
    return out


def images_from_pasteboard(pb):
    """Paths for whatever the pasteboard is carrying, pixels saved as PNG.

    A screenshot arrives as pixels, not text, so a plain paste would write
    nothing at all. A file keeps its own path — re-saving it would only make a
    second copy.

    Reading NSImage rather than asking for one flavour is what makes this hold
    up: a screenshot is TIFF, a browser hands over PNG, Preview can offer
    JPEG or HEIC, and NSImage takes all of them.
    """
    import AppKit
    from AppKit import NSImage

    out = files_from_pasteboard(pb)
    if out:
        return out

    blobs = []
    # A screenshot is already on the pasteboard as PNG; those bytes go to disk
    # as they are rather than through a decode and a re-encode.
    data = pb.dataForType_(getattr(AppKit, "NSPasteboardTypePNG", "public.png"))
    if data is not None:
        blobs.append(data)
    if not blobs:
        for image in pb.readObjectsForClasses_options_([NSImage], None) or []:
            data = png_data_from_image(image)
            if data is not None:
                blobs.append(data)
    if not blobs:
        # A last resort for anything NSImage would not read either.
        from AppKit import NSBitmapImageRep
        data = pb.dataForType_(getattr(AppKit, "NSPasteboardTypeTIFF",
                                       "public.tiff"))
        rep = NSBitmapImageRep.imageRepWithData_(data) if data else None
        if rep is not None:
            data = rep.representationUsingType_properties_(PNG_FILE_TYPE, {})
            if data is not None:
                blobs.append(data)

    for data in blobs:
        path = new_image_path()
        if data.writeToFile_atomically_(path, True):
            out.append(path)
    return out


def paste_check():
    """Report what the clipboard holds and whether an image can be saved.

    A paste that quietly does nothing has several possible causes — nothing on
    the pasteboard, no type we read, a conversion that failed, a write that
    failed — and from the outside they look the same.

    Every probe is reported separately because they disagree in practice:
    -types is deprecated and can come back empty on a pasteboard that plainly
    is not, so a single empty answer proves nothing on its own.
    """
    if not IS_MAC:
        sys.stderr.write("paste-check is macOS only\n")
        return 1
    try:
        from Foundation import NSURL
        from AppKit import NSPasteboard, NSImage, NSString
    except Exception as e:
        sys.stderr.write("PyObjC is missing (%s)\n" % e)
        return 1

    def probe(label, fn):
        try:
            print("%-22s %s" % (label + ":", fn()))
        except Exception as e:
            print("%-22s raised %s: %s" % (label + ":", type(e).__name__, e))

    pb = NSPasteboard.generalPasteboard()
    probe("changeCount", lambda: pb.changeCount())
    probe("types (deprecated)",
          lambda: ", ".join(str(t) for t in (pb.types() or [])) or "(empty)")

    items = []
    try:
        items = list(pb.pasteboardItems() or [])
    except Exception as e:
        print("pasteboardItems:      raised %s: %s" % (type(e).__name__, e))
    print("pasteboardItems:       %d" % len(items))
    for i, item in enumerate(items):
        for kind in (item.types() or []):
            data = item.dataForType_(kind)
            size = data.length() if data is not None else 0
            print("   item %d  %-34s %d bytes" % (i, str(kind), size))

    for label, cls in (("readable as text", NSString),
                       ("readable as image", NSImage),
                       ("readable as URL", NSURL)):
        probe(label, lambda c=cls: len(pb.readObjectsForClasses_options_([c], None) or []))

    try:
        paths = images_from_pasteboard(pb)
    except Exception:
        print("\nimages_from_pasteboard raised:")
        traceback.print_exc()
        return 1
    if not paths:
        print("\nno image found — a paste here would fall back to plain text")
        return 1
    for path in paths:
        size = os.path.getsize(path) if os.path.exists(path) else -1
        print("\nsaved: %s (%d bytes)" % (path, size))
    return 0


def start_mac_gui():
    """Run the macOS menu bar app. Returns False if PyObjC is unavailable."""
    try:
        import AppKit
        from Foundation import NSObject, NSTimer, NSURL, NSMakeRect
        from AppKit import (NSApplication, NSStatusBar, NSMenu, NSMenuItem,
                            NSImage, NSAlert, NSWorkspace, NSWindow, NSTextView,
                            NSScrollView, NSPopUpButton, NSButton, NSFont,
                            NSPasteboard, NSVariableStatusItemLength,
                            NSApplicationActivationPolicyAccessory)
    except Exception as e:
        sys.stderr.write(
            "ccdo: the menu bar app needs PyObjC (%s).\n"
            "    python3 -m pip install pyobjc-framework-Cocoa\n" % e)
        return False

    # Read the AppKit constants by name with a fallback: the modern spellings
    # (NSWindowStyleMaskTitled and friends) are missing from older PyObjC, and
    # a menu bar app should not fail to open a window over a renamed constant.
    def const(name, fallback):
        return getattr(AppKit, name, fallback)

    WINDOW_STYLE = (const("NSWindowStyleMaskTitled", 1)
                    | const("NSWindowStyleMaskClosable", 2)
                    | const("NSWindowStyleMaskResizable", 8))
    BACKING = const("NSBackingStoreBuffered", 2)
    WIDTH_SIZABLE = const("NSViewWidthSizable", 2)
    HEIGHT_SIZABLE = const("NSViewHeightSizable", 16)
    PIN_RIGHT = const("NSViewMinXMargin", 1)
    PIN_LEFT = const("NSViewMaxXMargin", 4)
    PIN_TOP = const("NSViewMaxYMargin", 32)
    BEZEL_BORDER = const("NSBezelBorder", 2)
    ROUNDED = const("NSRoundedBezelStyle", 1)
    DRAG_COPY = const("NSDragOperationCopy", 1)
    CMD_KEY = const("NSEventModifierFlagCommand", 1 << 20)
    SHIFT_KEY = const("NSEventModifierFlagShift", 1 << 17)
    CTRL_KEY = const("NSEventModifierFlagControl", 1 << 18)
    ALT_KEY = const("NSEventModifierFlagOption", 1 << 19)
    HUGE = 1.0e7

    cfg = load_config()
    load_language(cfg.get("language"))
    store = Store(cfg)

    class CcdoDispatch(NSObject):
        """One Objective-C target for every menu item.

        Each item carries a tag; the callable lives on the Python side. This
        keeps the bridge to a single selector instead of one per action.

        The method names are prefixed and reach Objective-C as "ccdoAction:"
        and "ccdoTick:" — a plain name like perform: risks colliding with a
        selector NSObject already answers to.
        """

        def ccdoAction_(self, sender):
            fn = _MAC_ACTIONS.get(sender.tag())
            if fn is None:
                return
            try:
                fn()
            except Exception as e:
                sys.stderr.write("[ccdo] menu action failed: %s\n" % e)

        def ccdoTick_(self, timer):
            try:
                app.refresh()
            except Exception as e:
                sys.stderr.write("[ccdo] refresh error: %s\n" % e)

        def windowWillClose_(self, note):
            """A closed note window gives its tags back."""
            window = note.object()
            for open_window in list(_MAC_WINDOWS):
                if open_window.win is window:
                    open_window.dismiss()

    dispatch = CcdoDispatch.alloc().init()
    SELECTOR = b"ccdoAction:"

    class CcdoTextView(NSTextView):
        """The note field, with paste taught about images.

        Everything else about it is a stock text view; only paste: is ours.
        """

        def paste_(self, sender):
            if DEBUG:
                sys.stderr.write("[ccdo] paste into the note window\n")
            try:
                paths = images_from_pasteboard(NSPasteboard.generalPasteboard())
            except Exception as e:
                sys.stderr.write("[ccdo] could not save the pasted image: %s\n" % e)
                paths = []
            if not paths:
                # Command+Shift+4 wrote a file and left the clipboard alone.
                shot = recent_screenshot(
                    int(cfg.get("screenshot_paste_seconds", 120)),
                    screenshot_dir(cfg))
                paths = [shot] if shot else []
            if not paths:
                self.pasteAsPlainText_(sender)
                return
            text = image_insert_text(paths, self.ccdoAtLineStart())
            self.insertText_replacementRange_(text, self.selectedRange())

        def performKeyEquivalent_(self, event):
            """Command+V and the rest of the editing keys.

            An accessory app has no menu bar, so there is no Edit menu to turn
            Command+V into paste: — which is why pasting into this window did
            nothing at all. The window's own key-equivalent chain does reach
            here, so the keys are answered directly.
            """
            flags = event.modifierFlags()
            if not (flags & CMD_KEY) or flags & (CTRL_KEY | ALT_KEY):
                return False
            key = str(event.charactersIgnoringModifiers() or "").lower()
            if key == "v":
                self.paste_(self)
            elif key == "c":
                self.copy_(self)
            elif key == "x":
                self.cut_(self)
            elif key == "a":
                self.selectAll_(self)
            elif key == "z":
                manager = self.undoManager()
                if manager is None:
                    return False
                manager.redo() if flags & SHIFT_KEY else manager.undo()
            else:
                # Command+Return belongs to the send button further down the
                # chain, and so does anything else we do not claim.
                return False
            return True

        def ccdoAcceptDrop_(self, sender):
            """Take whatever was dropped and write its path into the note."""
            try:
                paths = images_from_pasteboard(sender.draggingPasteboard())
            except Exception as e:
                sys.stderr.write("[ccdo] could not take the dropped file: %s\n" % e)
                return False
            if not paths:
                return False
            self.insertText_replacementRange_(
                image_insert_text(paths, self.ccdoAtLineStart()),
                self.selectedRange())
            return True

        def draggingEntered_(self, sender):
            return DRAG_COPY

        def draggingUpdated_(self, sender):
            return DRAG_COPY

        def prepareForDragOperation_(self, sender):
            return True

        def performDragOperation_(self, sender):
            # A plain text view would drop the bare path in, and a picture
            # dragged out of a browser not at all.
            return self.ccdoAcceptDrop_(sender)

        def ccdoAtLineStart(self):
            """Does the caret sit at the start of a line?"""
            where = self.selectedRange().location
            body = str(self.string())
            return where <= 0 or where > len(body) or body[where - 1] == "\n"

    def note_window(target, title):
        """Open (or raise) a note window aimed at one session."""
        for existing in _MAC_WINDOWS:
            if existing.target == target:
                existing.raise_()
                return
        NoteWindow(target, title).raise_()

    class NoteWindow(object):
        """A note as long as it needs to be, images included.

        The menu can only ever be a list; writing happens here. Paste a
        screenshot and its path lands in the text, which is what Claude Code
        reads once the task is handed over.
        """

        W, H, PAD, ROW = 560, 380, 14, 32

        def __init__(self, target, title):
            self.target = target
            self.tags = []
            self.closed = False

            self.choices = [(None, _("Inbox"))]
            for sess in app.sessions:
                if sess.get("live") and sess["target"] != INBOX:
                    self.choices.append((sess["target"], sess["label"]))
            if target is not None and target not in [t for t, __ in self.choices]:
                self.choices.append((target, target))

            self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, self.W, self.H), WINDOW_STYLE, BACKING, False)
            self.win.setTitle_(title)
            self.win.setReleasedWhenClosed_(False)
            self.win.setDelegate_(dispatch)
            self.win.center()
            content = self.win.contentView()

            body_h = self.H - self.PAD * 3 - self.ROW
            body_w = self.W - self.PAD * 2
            scroll = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(self.PAD, self.PAD * 2 + self.ROW, body_w, body_h))
            scroll.setHasVerticalScroller_(True)
            scroll.setBorderType_(BEZEL_BORDER)
            scroll.setAutoresizingMask_(WIDTH_SIZABLE | HEIGHT_SIZABLE)

            self.tv = CcdoTextView.alloc().initWithFrame_(
                NSMakeRect(0, 0, body_w, body_h))
            self.tv.setRichText_(False)
            # Smart quotes and dashes would rewrite pasted code and paths.
            self.tv.setAutomaticQuoteSubstitutionEnabled_(False)
            self.tv.setAutomaticDashSubstitutionEnabled_(False)
            self.tv.setAllowsUndo_(True)
            self.tv.setFont_(NSFont.systemFontOfSize_(13.0))
            self.tv.setMinSize_((0.0, 0.0))
            self.tv.setMaxSize_((HUGE, HUGE))
            self.tv.setVerticallyResizable_(True)
            self.tv.setHorizontallyResizable_(False)
            self.tv.setAutoresizingMask_(WIDTH_SIZABLE)
            self.tv.registerForDraggedTypes_(
                [const("NSPasteboardTypeFileURL", "public.file-url"),
                 const("NSPasteboardTypePNG", "public.png"),
                 const("NSPasteboardTypeTIFF", "public.tiff")])
            self.tv.textContainer().setContainerSize_((body_w, HUGE))
            self.tv.textContainer().setWidthTracksTextView_(True)
            scroll.setDocumentView_(self.tv)
            content.addSubview_(scroll)

            self.picker = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(self.PAD, self.PAD, 240, self.ROW - 4), False)
            for __, label in self.choices:
                self.picker.addItemWithTitle_(label)
            self.picker.selectItemAtIndex_(
                [t for t, __ in self.choices].index(target))
            self.picker.setAutoresizingMask_(PIN_RIGHT | PIN_TOP)
            content.addSubview_(self.picker)

            self.button(_("Add"), self.W - self.PAD - 220, 100,
                        lambda: self.submit(False))
            # Command+Return sends: Return alone belongs to the text.
            self.button(_("Add and send"), self.W - self.PAD - 110, 110,
                        lambda: self.submit(True), "\r", CMD_KEY)

        def button(self, title, x, width, fn, key="", mask=0):
            b = NSButton.alloc().initWithFrame_(
                NSMakeRect(x, self.PAD - 2, width, self.ROW))
            b.setTitle_(title)
            b.setBezelStyle_(ROUNDED)
            tag = mac_action(fn)
            self.tags.append(tag)
            b.setTag_(tag)
            b.setTarget_(dispatch)
            b.setAction_(SELECTOR)
            if key:
                b.setKeyEquivalent_(key)
                b.setKeyEquivalentModifierMask_(mask)
            b.setAutoresizingMask_(PIN_LEFT | PIN_TOP)
            self.win.contentView().addSubview_(b)
            return b

        def raise_(self):
            if self not in _MAC_WINDOWS:
                _MAC_WINDOWS.append(self)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            self.win.makeKeyAndOrderFront_(None)
            self.win.makeFirstResponder_(self.tv)

        def submit(self, send):
            text = str(self.tv.string()).strip()
            if not text:
                return
            target = self.choices[self.picker.indexOfSelectedItem()][0]
            task = store.add(text, target=target)
            if task and send and target:
                ok, msg = deliver(cfg, store, task)
                notify("ccdo", msg, cfg)
            self.dismiss()
            self.win.close()
            app.refresh(force=True)

        def dismiss(self):
            """Give the tags back. Closing can arrive twice — by button and by
            the window delegate — so this has to be harmless the second time.
            """
            if self.closed:
                return
            self.closed = True
            for tag in self.tags:
                _MAC_ACTIONS.pop(tag, None)
            if self in _MAC_WINDOWS:
                _MAC_WINDOWS.remove(self)

    class MenuBarApp(object):
        def __init__(self):
            self.sessions = []
            self.signature = None
            self.tags = []
            bar = NSStatusBar.systemStatusBar()
            self.item = bar.statusItemWithLength_(NSVariableStatusItemLength)
            icon = NSImage.alloc().initWithContentsOfFile_(write_icons(True))
            if icon is not None:
                icon.setSize_((18, 18))
                # A template image is recoloured by macOS, so it stays legible
                # whether the menu bar is light or dark.
                icon.setTemplate_(True)
                self.item.button().setImage_(icon)
            else:
                self.item.button().setTitle_("ccdo")
            self.menu = NSMenu.alloc().init()
            self.menu.setAutoenablesItems_(False)
            self.item.setMenu_(self.menu)

        # -- building ------------------------------------------------- #

        def add(self, menu, title, fn=None, enabled=True):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, SELECTOR if fn else None, "")
            if fn:
                tag = mac_action(fn)
                self.tags.append(tag)
                item.setTag_(tag)
                item.setTarget_(dispatch)
            item.setEnabled_(bool(enabled and fn))
            menu.addItem_(item)
            return item

        def separator(self, menu):
            menu.addItem_(NSMenuItem.separatorItem())

        def build(self):
            # Only the menu's own actions go: an open note window keeps its
            # buttons working across a rebuild.
            for tag in self.tags:
                _MAC_ACTIONS.pop(tag, None)
            self.tags = []
            self.menu.removeAllItems()

            latest = read_update_cache().get("latest", "")
            if newer_version(latest):
                self.add(self.menu, "⬆  " + _("Update available: %s") % latest,
                         self.show_update)
                self.separator(self.menu)

            self.add(self.menu, _("Quick note…"),
                     lambda: note_window(None, _("Quick note")))
            self.separator(self.menu)

            shown = 0
            for sess in self.sessions:
                tasks = store.pending(sess["target"])
                if sess["target"] == INBOX and not tasks:
                    continue
                shown += 1
                mark = "" if sess.get("live") else "  (%s)" % _("closed")
                head = self.add(self.menu, "%s — %d%s"
                                % (sess["label"], len(tasks), mark), None)
                sub = NSMenu.alloc().init()
                sub.setAutoenablesItems_(False)
                head.setSubmenu_(sub)
                head.setEnabled_(True)

                if sess.get("live") and sess["target"] != INBOX:
                    target = sess["target"]
                    self.add(sub, _("Note for this session…"),
                             lambda t=target, name=sess["label"]:
                             note_window(t, name))
                    self.add(sub, _("Send next task"),
                             lambda t=target: self.send_next(t), bool(tasks))
                    self.separator(sub)
                if not tasks:
                    self.add(sub, "(%s)" % _("empty"), None)
                for task in tasks[:10]:
                    line = task["text"].strip().splitlines()[0][:48]
                    if int(task.get("priority", 0)) > 0:
                        line = "★ " + line
                    row = self.add(sub, line, None)
                    acts = NSMenu.alloc().init()
                    acts.setAutoenablesItems_(False)
                    row.setSubmenu_(acts)
                    row.setEnabled_(True)
                    tid = task["id"]
                    self.add(acts, _("Send"), lambda i=tid: self.send_task(i))
                    self.add(acts, _("Done"), lambda i=tid: self.mark_done(i))
                    self.add(acts, _("Delete"), lambda i=tid: self.delete(i))

            if not shown:
                self.add(self.menu, "(%s)" % _("no live sessions"), None)

            self.separator(self.menu)
            self.add(self.menu, _("Scan sessions"), lambda: self.refresh(force=True))
            self.add(self.menu, _("Clear completed"),
                     lambda: (store.purge_done(), self.refresh(force=True)))
            self.add(self.menu, _("Queue file"), lambda: open_in_editor(QUEUE_MD))
            self.add(self.menu, _("Decision log"), lambda: open_in_editor(EVENTS_PATH))
            self.add(self.menu, _("Open the settings file"),
                     lambda: open_in_editor(CONFIG_PATH))
            self.separator(self.menu)
            self.add(self.menu, "ccdo %s" % VERSION, None)
            self.add(self.menu, _("Quit"), lambda:
                     NSApplication.sharedApplication().terminate_(None))

        # -- actions --------------------------------------------------- #

        def send_task(self, task_id):
            task = next((t for t in store.all() if t["id"] == task_id), None)
            if task:
                ok, msg = deliver(cfg, store, task)
                notify("ccdo", msg, cfg)
            self.refresh(force=True)

        def send_next(self, target):
            task = store.next_pending(target)
            if task is None:
                return
            self.send_task(task["id"])

        def mark_done(self, task_id):
            store.update(task_id, status="done")
            self.refresh(force=True)

        def delete(self, task_id):
            store.delete(task_id)
            self.refresh(force=True)

        def show_update(self):
            cache = read_update_cache()
            alert = NSAlert.alloc().init()
            alert.setMessageText_(_("ccdo %s is out (you have %s)")
                                  % (cache.get("latest", ""), VERSION))
            alert.setInformativeText_(plain_markdown(cache.get("notes"))
                                      or _("No release notes."))
            alert.addButtonWithTitle_(_("Open on GitHub"))
            alert.addButtonWithTitle_(_("Close"))
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            if alert.runModal() == 1000:
                NSWorkspace.sharedWorkspace().openURL_(
                    NSURL.URLWithString_(RELEASES_URL))

        # -- refreshing ------------------------------------------------ #

        def refresh(self, force=False):
            self.sessions = discover_sessions(cfg)
            signature = tuple(
                (s["label"], s["target"], bool(s.get("live")),
                 tuple(t["id"] for t in store.pending(s["target"])))
                for s in self.sessions)
            signature += (read_update_cache().get("latest", ""),)
            if not force and signature == self.signature:
                return
            self.signature = signature
            self.build()
            pending = len(store.pending())
            self.item.button().setToolTip_(_("ccdo — %d waiting") % pending)

    ns_app = NSApplication.sharedApplication()
    # An accessory app lives in the menu bar with no Dock icon and no menu of
    # its own, which is what a status item should be.
    ns_app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    app = MenuBarApp()
    app.refresh(force=True)
    # On its own thread: the icon should appear at once, not after the network
    # has had its say. The timer picks the answer up out of the cache.
    if cfg.get("check_updates", True):
        threading.Thread(target=lambda: check_update(cfg), daemon=True).start()

    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        2.0, dispatch, b"ccdoTick:", None, True)
    ns_app.run()
    return True


# --------------------------------------------------------------------------- #
#  GUI
# --------------------------------------------------------------------------- #

def start_gui(use_statusicon=False):
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk, Gdk, GLib, Pango
    except (ImportError, ValueError) as e:
        # The tray needs GTK and a Linux desktop. Everything else — the queue,
        # the hooks, delivery over tmux — runs without it, so say what is
        # missing rather than dying with an import trace.
        sys.stderr.write(
            "ccdo: the tray window needs GTK 3 and is Linux-only (%s).\n"
            "The queue and the Claude Code hooks work without it:\n"
            "    ccdo add \"a note\"   ccdo list   ccdo next   ccdo install-hooks\n"
            % e)
        return 1

    # Without these the app introduces itself by its interpreter: the macOS
    # menu bar and the Dock both showed "python".
    GLib.set_prgname(APP_NAME)
    GLib.set_application_name(APP_NAME)

    Indicator = None
    if not use_statusicon:
        for ns in ("AyatanaAppIndicator3", "AppIndicator3"):
            try:
                gi.require_version(ns, "0.1")
                Indicator = getattr(__import__("gi.repository", fromlist=[ns]), ns)
                break
            except (ValueError, ImportError, AttributeError):
                continue
        if Indicator is None:
            sys.stderr.write("No AppIndicator, falling back to StatusIcon.\n")
            use_statusicon = True

    cfg = load_config()
    load_language(cfg.get("language"))
    store = Store(cfg)
    ensure_dirs()
    icon_path = write_icons()

    # The design language comes out of one token set. Repeating colors rule by
    # rule meant a tone fixed in one window stayed stale in another; now every
    # surface feeds from the same table.
    def build_css(theme):
        # The send button's text color is derived from its background; fixed
        # dark text disappeared on the darker tones in the palette.
        theme = dict(theme, send_ink=ink_for(theme["accent"]))
        return """
    /* --- ground -------------------------------------------------------- */
    .jd-window {{ background: {bg}; color: {text}; }}

    /* The frame GTK draws around a client-side-decorated window. Left to the
       theme it came up light, which on macOS showed as a pale border around
       the whole window. */
    .jd-window decoration {{ background: {bg}; border: 1px solid {border_soft}; }}

    /* Title bar: only the background is ours. We leave the close/minimise/
       maximise buttons alone — those are the desktop's own and have to look
       like it. That is why every element-level rule sits under .jd-body: put
       under .jd-window, our provider priority would beat the theme and
       flatten the titlebuttons too. */
    .jd-window headerbar {{ background: {bg}; box-shadow: none;
                            border-bottom: 1px solid {border_soft};
                            min-height: 36px; padding: 0 6px; }}
    .jd-window headerbar .title {{ font-size: 11px; font-weight: 700;
                                   color: {dim}; }}
    .jd-body label {{ color: {text}; }}
    .jd-body separator {{ background: {border_soft}; min-width: 1px;
                            min-height: 1px; }}

    /* --- type ---------------------------------------------------------- */
    .jd-head {{ font-weight: 700; font-size: 12px; letter-spacing: 1px;
                color: {text}; }}
    .jd-sub {{ font-size: 10px; color: {dim}; font-family: {mono}; }}
    .jd-hint {{ font-size: 10px; color: {faint}; }}
    .jd-meta {{ font-size: 10px; color: {faint}; font-family: {mono}; }}
    .jd-empty {{ font-size: 11px; color: {faint}; }}
    .jd-task {{ color: {text}; }}
    .jd-task-sent {{ color: {faint}; }}
    .jd-num {{ font-family: {mono}; font-size: 11px; color: {faint}; }}
    .jd-num-next {{ font-family: {mono}; font-size: 12px; font-weight: 700;
                    color: {accent}; }}
    .jd-dead .jd-head {{ color: {faint}; }}

    /* --- notice: the one colored element, set apart by its border ------- */
    .jd-notice {{ font-size: 11px; color: {warn};
                  background: {warn_bg};
                  border: 1px solid {warn_edge};
                  border-radius: {r_lg}; padding: 7px 9px; }}

    /* --- session card: header and note box on one surface -------------- */
    .jd-sesscard {{ background: {surface}; border: 1px solid {border_soft};
                    border-radius: {r_lg}; padding: 14px 16px; }}
    .jd-title {{ font-size: 15px; font-weight: 800; color: {accent}; }}
    .jd-statedot {{ font-size: 9px; color: {accent}; }}

    /* Identity details as readable chips rather than one long line. */
    .jd-chip {{ background: {raised}; border: 1px solid {border};
                border-radius: 11px; padding: 3px 10px; font-size: 10px;
                color: {dim}; }}
    .jd-tabicon {{ color: {dim}; }}
    .jd-more {{ background: transparent; border-color: transparent;
                color: {faint}; padding: 2px 6px; }}
    .jd-more:hover {{ color: {text}; background: {raised}; }}
    .jd-divider {{ background: {border_soft}; min-height: 1px; }}

    /* --- task card ------------------------------------------------------ */
    .jd-taskcard {{ background: {surface}; border: 1px solid {border_soft};
                    border-radius: {r_lg}; padding: 6px 8px;
                    margin-bottom: 8px; }}
    .jd-taskcard:hover {{ background: {raised}; border-color: {border}; }}
    .jd-time {{ font-size: 10px; color: {faint}; font-family: {mono}; }}

    /* --- add row -------------------------------------------------------- */
    .jd-body .jd-addbtn {{ background: transparent; color: {accent};
                  border: 1px solid {accent}; border-radius: {r_md};
                  font-weight: 700; padding: 6px 18px; }}
    .jd-body .jd-addbtn:hover {{ background: {accent_wash}; }}

    /* --- primary action in the bottom bar ------------------------------- */
    .jd-body .jd-send {{ font-weight: 800; font-size: 12px; padding: 12px 18px;
                border: none; border-radius: {r_lg};
                background: {accent}; color: {send_ink}; }}
    /* The symbolic icon took its color from the theme; we bind it to the
       label color and let the box spacing open the gap. */
    .jd-body .jd-send label {{ color: {send_ink}; }}
    .jd-body .jd-sendicon {{ color: {send_ink}; }}
    .jd-otolbl {{ font-size: 11px; font-weight: 800; color: {text}; }}
    .jd-footbar {{ border-top: 1px solid {border_soft}; padding-top: 12px; }}

    /* --- card: groups settings that belong together -------------------- */
    .jd-card {{ background: {surface}; border: 1px solid {border_soft};
                border-radius: {r_lg}; padding: 10px 12px; }}
    .jd-section {{ font-size: 10px; font-weight: 700; color: {dim};
                   letter-spacing: 1px; }}

    /* --- row icons: one color, brightening on hover -------------------- */
    .jd-body .jd-rowbtn {{ color: {dim}; font-size: 13px; padding: 2px 7px;
                  background: transparent; border-color: transparent; }}
    .jd-body .jd-rowbtn:hover {{ color: {text}; background: {raised}; }}
    /* The auto row is separated from the send button by a rule: harder to
       hit by mistake, and it reads as a mode rather than an action. */
    .jd-autorow {{ border-top: 1px solid {border_soft}; padding-top: 10px;
                   margin-top: 4px; }}
    .jd-body .jd-star {{ color: {dim}; background: transparent;
                         border: 1px solid {border}; border-radius: {r_md};
                         padding: 6px 10px; }}
    .jd-body .jd-star:checked {{ color: {accent}; border-color: {accent};
                                 background: transparent; }}

    /* --- checkbox / switch: not left to the system theme's accent -------
       On Ubuntu the checked box was drawn green and the switch orange;
       neither came from the app's palette. */
    .jd-body switch {{ background: {raised}; border: 1px solid {border};
                         border-radius: 14px; }}
    .jd-body switch:checked {{ background: {accent}; border-color: {accent}; }}
    .jd-body switch slider {{ background: {text}; border: none;
                                border-radius: 50%; margin: 1px;
                                min-width: 16px; min-height: 16px; }}
    .jd-body switch:checked slider {{ background: {accent_ink}; }}
    .jd-body checkbutton {{ color: {dim}; font-size: 11px; }}
    .jd-body checkbutton check {{ background: {raised}; color: {text};
                                    border: 1px solid {border};
                                    border-radius: 4px;
                                    min-width: 14px; min-height: 14px; }}
    .jd-body checkbutton check:checked {{ background: {accent};
                                            border-color: {accent};
                                            color: {accent_ink}; }}

    /* --- inputs --------------------------------------------------------- */
    .jd-input {{ font-family: {mono}; font-size: 13px; padding: 7px;
                 background: {sunken}; color: {text};
                 border: 1px solid {border}; border-radius: {r_lg}; }}
    .jd-input text {{ background: transparent; color: {text}; }}
    .jd-input:focus {{ border-color: {accent}; }}
    .jd-body entry {{ background: {surface}; color: {text};
                        border: 1px solid {border}; border-radius: {r_md};
                        padding: 4px 8px; }}
    .jd-body entry:focus {{ border-color: {accent}; }}
    .jd-body spinbutton {{ background: {surface}; color: {text};
                             border: 1px solid {border};
                             border-radius: {r_md}; }}
    .jd-body spinbutton entry {{ border: none; background: transparent; }}
    .jd-body spinbutton button {{ border: none; background: transparent;
                                    padding: 0 6px; }}
    .jd-body combobox button {{ background: {surface};
                                  border: 1px solid {border};
                                  border-radius: {r_md}; }}

    /* --- buttons -------------------------------------------------------- */
    .jd-body button {{ background: {raised}; color: {text}; font-size: 12px;
                         border: 1px solid {border}; border-radius: {r_md};
                         padding: 5px 12px; }}
    .jd-body button:hover {{ background: {raised_hi}; }}
    .jd-body button:active {{ background: {border}; }}
    .jd-body button:disabled {{ background: {surface}; color: {faint};
                                  border-color: {border_soft}; }}
    .jd-body button.flat {{ background: transparent;
                              border-color: transparent; padding: 2px 6px; }}
    .jd-body button.flat:hover {{ background: {raised};
                                    border-color: {border_soft}; }}
    .jd-body button.suggested-action {{ background: {accent};
                                          color: {accent_ink};
                                          border-color: {accent};
                                          font-weight: 700; }}
    .jd-body button.suggested-action:hover {{ background: {accent_hi};
                                                border-color: {accent_hi}; }}
    .jd-body .jd-arrow {{ font-size: 8px; padding: 0px; min-height: 10px;
                 border: none; background: transparent; }}
    .jd-body .jd-arrow:hover {{ background: {raised}; }}

    /* --- rows ----------------------------------------------------------- */
    .jd-row {{ border-bottom: 1px solid {border_soft}; padding: 2px 0; }}
    .jd-row:hover {{ background: {surface}; }}
    .jd-body list {{ background: transparent; }}

    /* --- tabs ----------------------------------------------------------- */
    /* Without a background on the page area GTK's theme supplies one: it
       happened to match under the dark palette, so nobody noticed, but on
       the light one the bottom half of the window stayed pitch black. */
    notebook.jd-body {{ background: {bg}; }}
    notebook.jd-body > stack {{ background: {bg}; }}
    notebook.jd-body > header {{ background: {bg}; border: none; }}
    notebook.jd-body > header > tabs > tab {{ border: none; padding: 9px 14px;
                                                 color: {dim}; font-size: 12px;
                                                 min-height: 0;
                                                 border-radius: {r_lg} {r_lg} 0 0; }}
    notebook.jd-body > header > tabs > tab:hover {{ background: {surface}; }}
    /* The selected tab's underline came from the system theme (green on
       Ubuntu); we override it with our own accent. */
    notebook.jd-body > header > tabs > tab:checked {{ color: {text};
                                                         font-weight: 700;
                                                         background: {surface};
                                                         box-shadow: inset 0 -3px {accent}; }}

    /* --- history expander ----------------------------------------------- */
    .jd-body expander title {{ color: {dim}; font-size: 11px; }}

    /* --- scrollbar ------------------------------------------------------ */
    .jd-body scrollbar {{ background: transparent; border: none; }}
    .jd-body scrollbar slider {{ background: {border}; border-radius: 6px;
                                   min-width: 6px; min-height: 24px; }}
    .jd-body scrollbar slider:hover {{ background: {raised_hi}; }}
        """.format(**theme)

    base_prov = Gtk.CssProvider()
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), base_prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    gtk_settings = Gtk.Settings.get_default()
    theme = {}
    app_ref = {}

    def apply_theme(*_):
        """Match the palette to the desktop's light/dark preference.

        A fixed dark palette left an unreadable window under a light theme.
        The preference can also change mid-session (one click on GNOME), so we
        subscribe to the setting and reload the CSS.
        """
        new = active_theme(gtk_settings)
        if new is theme.get("_src"):
            return
        theme.clear()
        theme.update(new)
        theme["_src"] = new
        try:
            base_prov.load_from_data(build_css(new).encode())
        except Exception as e:
            sys.stderr.write("tema css: %s\n" % e)
        rebuild_accent_css(getattr(app_ref.get("app"), "sessions", []) or [])

    if gtk_settings is not None:
        for prop in ("notify::gtk-theme-name",
                     "notify::gtk-application-prefer-dark-theme"):
            gtk_settings.connect(prop, apply_theme)

    accent_prov = Gtk.CssProvider()
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), accent_prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

    def rebuild_accent_css(sessions):
        # Named fields instead of positional %s: adding a rule can no longer
        # shift the argument count out from under the others.
        tpl = (
            ".jd-a-{k} .jd-head {{ color: {c}; }}\n"
            ".jd-a-{k} .jd-title {{ color: {c}; }}\n"
            ".jd-a-{k} .jd-statedot {{ color: {c}; }}\n"
            ".jd-a-{k} .jd-bar {{ background: {c}; }}\n"
            ".jd-a-{k} .jd-dot {{ background: {c}; border-radius: 5px; }}\n"

            ".jd-a-{k} .jd-input:focus {{ border-color: {c}; }}\n"
            ".jd-a-{k} .jd-addbtn {{ color: {c}; border-color: {c}; }}\n"
            ".jd-a-{k} .jd-addbtn:hover {{ background: {faint}; }}\n"
            ".jd-a-{k} .jd-star:checked {{ color: {c}; }}\n"
            ".jd-a-{k} .jd-send {{ background: {soft}; color: {ink};"
            " font-weight: 800; border: none; }}\n"
            ".jd-a-{k} .jd-send label {{ color: {ink}; }}\n"
            ".jd-a-{k} .jd-sendicon {{ color: {ink}; }}\n"
            ".jd-a-{k} .jd-send:hover {{ background: {c}; }}\n"
            ".jd-a-{k} switch:checked {{ background: {c}; border-color: {c}; }}\n"
            ".jd-a-{k} .jd-row {{ border-left: 2px solid {edge}; }}\n"
            ".jd-a-{k} .jd-num-next {{ color: {c}; }}\n"
            # Underline the selected tab in that session's color. We cannot
            # put a class on the tab node, so the class sits on the Notebook
            # and is updated as the page changes.
            "notebook.jd-nb-{k} > header > tabs > tab:checked"
            " {{ box-shadow: inset 0 -3px {c}; }}\n"
        )
        chunks = []
        for s in sessions:
            c = s["color"]
            chunks.append(tpl.format(k=slug(s["target"]), c=c,
                                     ink=ink_for(c),
                                     faint=hex_to_rgba(c, 0.06),
                                     soft=hex_to_rgba(c, 0.85),
                                     edge=hex_to_rgba(c, 0.35)))
        try:
            accent_prov.load_from_data("".join(chunks).encode())
        except Exception as e:
            sys.stderr.write("accent css: %s\n" % e)

    apply_theme()

    # ------------------------------------------------------------------ #

    def add_headerbar(dialog, title):
        """Give a dialog the desktop's own title bar and close button.

        Without one, mutter draws a plain frame whose buttons look nothing
        like the ones on the main window.
        """
        head = Gtk.HeaderBar()
        head.set_show_close_button(True)
        head.set_title(title)
        head.set_has_subtitle(False)
        dialog.set_titlebar(head)

    def mark_body(dialog):
        """Mark a dialog's content and button strip with .jd-body.

        Element-level rules (button, entry, switch…) live under .jd-body
        rather than .jd-window, because every window here has a HeaderBar and
        .jd-window would drag the title bar's close/minimise/maximise buttons
        into our flat button style when they have to look like the desktop's
        own. Marking the two strips rather than the dialog keeps the title bar
        outside our reach: a dialog's content area is a direct child of the
        dialog on this GTK version, so a class put there would cover it.
        """
        parts = [dialog.get_content_area()]
        try:
            parts.append(dialog.get_action_area())
        except Exception:
            pass
        for part in parts:
            if part is not None:
                part.get_style_context().add_class("jd-body")

    def insert_image_paths(tv, paths):
        buf = tv.get_buffer()
        buf.delete_selection(True, tv.get_editable())
        at = buf.get_iter_at_mark(buf.get_insert())
        buf.insert_at_cursor(image_insert_text(paths, at.starts_line()))

    def attach_image_paste(tv):
        """Write a pasted image to disk and put its path into the note.

        When a screenshot arrives via Ctrl+V the clipboard carries an image,
        not text, and the default paste writes nothing at all. We save it as
        PNG and insert the path, so Claude can read the image once the task is
        handed over.
        """
        def on_paste(widget):
            clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            paths = []
            if clip.wait_is_image_available():
                pixbuf = clip.wait_for_image()
                if pixbuf is None:
                    return
                try:
                    paths = [save_pasted_image(pixbuf)]
                except Exception as e:
                    sys.stderr.write("ccdo: could not save image: %s\n" % e)
                    return
            elif clip.wait_is_uris_available():
                paths = file_paths_from_uris(clip.wait_for_uris())
            if not paths:
                shot = recent_screenshot(
                    int(cfg.get("screenshot_paste_seconds", 120)),
                    screenshot_dir(cfg))
                paths = [shot] if shot else []
            if not paths:
                return
            insert_image_paths(widget, paths)
            widget.emit_stop_by_name("paste-clipboard")

        tv.connect("paste-clipboard", on_paste)

    def attach_file_drop(tv):
        """Take a file dropped on the note and write its path into it.

        A text view drops the URI in as text of its own accord, which is not
        the same thing: the path has to be quoted and on a line of its own,
        the way a pasted one is.
        """
        def on_drop(widget, context, x, y, data, info, time_):
            paths = file_paths_from_uris(data.get_uris())
            if not paths:
                return
            insert_image_paths(widget, paths)
            Gtk.drag_finish(context, True, False, time_)
            widget.emit_stop_by_name("drag-data-received")

        tv.drag_dest_add_uri_targets()
        tv.connect("drag-data-received", on_drop)

    class SessionPage(Gtk.Box):
        """Note box and queue for a single Claude Code session."""

        def __init__(self, app, sess):
            super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.app = app
            self.sess = sess
            self.get_style_context().add_class("jd-a-%s" % slug(sess["target"]))
            if not sess.get("live"):
                self.get_style_context().add_class("jd-dead")

            bar = Gtk.DrawingArea()
            bar.set_size_request(-1, 3)
            bar.get_style_context().add_class("jd-bar")
            self.pack_start(bar, False, False, 0)

            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            inner.set_border_width(10)
            self.pack_start(inner, True, True, 0)

            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            card.get_style_context().add_class("jd-sesscard")
            card.set_margin_bottom(10)
            inner.pack_start(card, False, False, 0)

            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.title_lbl = Gtk.Label(xalign=0)
            self.title_lbl.get_style_context().add_class("jd-title")
            self.title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            self.title_lbl.set_max_width_chars(24)
            self.title_lbl.set_width_chars(6)
            head.pack_start(self.title_lbl, True, True, 0)
            self.state_dot = Gtk.Label(label="●", xalign=1)
            self.state_dot.get_style_context().add_class("jd-statedot")
            self.state_dot.set_valign(Gtk.Align.CENTER)
            more = Gtk.Button()
            more.set_image(Gtk.Image.new_from_icon_name(
                "view-more-symbolic", Gtk.IconSize.BUTTON))
            more.set_relief(Gtk.ReliefStyle.NONE)
            more.get_style_context().add_class("jd-more")
            more.set_tooltip_text(_("Session actions"))
            more.connect("clicked", self.on_more)
            head.pack_end(more, False, False, 0)
            self.state_lbl = Gtk.Label(label="", xalign=1)
            self.state_lbl.get_style_context().add_class("jd-sub")
            head.pack_end(self.state_lbl, False, False, 0)
            head.pack_end(self.state_dot, False, False, 0)
            card.pack_start(head, False, False, 0)

            # As one long line these details went unread; each part now sits
            # in its own chip.
            self.chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            card.pack_start(self.chips, False, False, 0)

            self.path_lbl = None
            if sess.get("cwd"):
                self.path_lbl = Gtk.Label(xalign=0)
                self.path_lbl.get_style_context().add_class("jd-sub")
                self.path_lbl.set_ellipsize(Pango.EllipsizeMode.START)
                self.path_lbl.set_max_width_chars(34)
                self.path_lbl.set_width_chars(10)
                card.pack_start(self.path_lbl, False, False, 0)

            self.apply_session(sess)

            self.tv = Gtk.TextView()
            self.tv.set_buffer(app.buffer_for(sess["target"]))
            self.tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self.tv.get_style_context().add_class("jd-input")
            self.tv.connect("key-press-event", self.on_tv_key)
            attach_image_paste(self.tv)
            attach_file_drop(self.tv)
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sw.set_size_request(-1, 110)
            if hasattr(sw, "set_propagate_natural_width"):
                sw.set_propagate_natural_width(False)
            sw.add(self.tv)
            # A placeholder telling you what an empty box is for. TextView
            # has none, so it is a label overlaid on top.
            self.ph = Gtk.Label(label=_("Click to add a note…"), xalign=0,
                                yalign=0)
            self.ph.get_style_context().add_class("jd-hint")
            self.ph.set_margin_start(11)
            self.ph.set_margin_top(9)
            self.ph.set_no_show_all(True)
            overlay = Gtk.Overlay()
            overlay.add(sw)
            overlay.add_overlay(self.ph)
            overlay.set_overlay_pass_through(self.ph, True)
            card.pack_start(overlay, False, False, 0)
            self.tv.get_buffer().connect("changed", self.sync_placeholder)
            self.sync_placeholder()

            div = Gtk.DrawingArea()
            div.set_size_request(-1, 1)
            div.get_style_context().add_class("jd-divider")
            card.pack_start(div, False, False, 0)

            bar2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hint = Gtk.Label(label=_("Enter: Add  •  Ctrl+Enter: Add + Send  •  "
                                     "Shift+Enter: Newline  •  Ctrl+V: Image"),
                             xalign=0)
            hint.get_style_context().add_class("jd-hint")
            hint.set_ellipsize(Pango.EllipsizeMode.END)
            hint.set_max_width_chars(30)
            hint.set_width_chars(6)
            hint.set_valign(Gtk.Align.CENTER)
            bar2.pack_start(hint, True, True, 0)
            self.star = Gtk.ToggleButton()
            self.star.set_image(Gtk.Image.new_from_icon_name(
                "non-starred-symbolic", Gtk.IconSize.BUTTON))
            self.star.set_tooltip_text(_("Starred"))
            self.star.get_style_context().add_class("jd-star")
            self.star.connect("toggled", self.on_star)
            bar2.pack_end(self.star, False, False, 0)
            add = Gtk.Button(label=_("Add"))
            add.get_style_context().add_class("jd-addbtn")
            add.connect("clicked", lambda *_: self.add_note(False))
            bar2.pack_end(add, False, False, 0)
            card.pack_start(bar2, False, False, 0)

            self.notice = Gtk.Label(label="", xalign=0)
            self.notice.get_style_context().add_class("jd-notice")
            self.notice.set_line_wrap(True)
            self.notice.set_max_width_chars(44)
            self.notice.set_no_show_all(True)
            inner.pack_start(self.notice, False, False, 0)

            self.listbox = Gtk.ListBox()
            self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
            lsw = Gtk.ScrolledWindow()
            lsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            # Letting the natural width/height propagate to the box above can
            # put the window into a grow-shrink loop; we pin it.
            for setter, val in (("set_propagate_natural_width", False),
                                ("set_propagate_natural_height", False)):
                if hasattr(lsw, setter):
                    getattr(lsw, setter)(val)
            lsw.set_min_content_height(120)
            lsw.add(self.listbox)
            inner.pack_start(lsw, True, True, 0)

            # History starts collapsed so the window height does not jump.
            # It is filled only while open — building rows behind a closed
            # expander would be wasted work on every refresh.
            self.hist_box = Gtk.ListBox()
            self.hist_box.set_selection_mode(Gtk.SelectionMode.NONE)
            hsw = Gtk.ScrolledWindow()
            hsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            for setter, val in (("set_propagate_natural_width", False),
                                ("set_propagate_natural_height", False)):
                if hasattr(hsw, setter):
                    getattr(hsw, setter)(val)
            hsw.set_min_content_height(150)
            hsw.add(self.hist_box)
            self.hist_exp = Gtk.Expander(label=_("History"))
            self.hist_exp.set_tooltip_text(
                _("Tasks completed (✓) and deleted (✕) in this session.\n"
                  "All of them: ccdo history — or HISTORY.md"))
            self.hist_exp.add(hsw)
            self.hist_exp.connect("notify::expanded", self.on_hist_toggle)
            inner.pack_start(self.hist_exp, False, False, 0)

            # Bottom bar: the mode switch on the left, the primary action on
            # the right. "auto" used to be a small checkbox right beside the
            # send button — a narrow target, and "send now" sat next to
            # "change the mode", so hitting the wrong one was easy. At
            # opposite ends of the window that mistake is hard to make.
            foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            foot.get_style_context().add_class("jd-footbar")
            self.auto = Gtk.Switch()
            self.auto.set_valign(Gtk.Align.CENTER)
            self.auto.set_sensitive(bool(sess.get("session_id")))
            self.auto_handler = self.auto.connect("state-set", self.on_auto)
            foot.pack_start(self.auto, False, False, 0)
            auto_lbl = Gtk.Label(label=_("AUTO"), xalign=0)
            auto_lbl.get_style_context().add_class("jd-otolbl")
            auto_lbl.set_valign(Gtk.Align.CENTER)
            foot.pack_start(auto_lbl, False, False, 0)
            self.auto_hint = Gtk.Label(label="", xalign=0)
            self.auto_hint.get_style_context().add_class("jd-hint")
            self.auto_hint.set_ellipsize(Pango.EllipsizeMode.END)
            self.auto_hint.set_max_width_chars(30)
            self.auto_hint.set_valign(Gtk.Align.CENTER)
            foot.pack_start(self.auto_hint, False, False, 0)
            info = Gtk.Image.new_from_icon_name("dialog-information-symbolic",
                                                Gtk.IconSize.MENU)
            info.get_style_context().add_class("jd-tabicon")
            info.set_valign(Gtk.Align.CENTER)
            info.set_tooltip_text(
                _("When on, Claude takes the next queued task by itself at the end "
                  "of every turn. At most max_auto_advance in a row; your "
                  "message resets the counter."))
            foot.pack_start(info, False, False, 0)
            foot.pack_start(Gtk.Box(), True, True, 0)

            direct = is_tmux_target(sess["target"])
            # The button's own icon+label layout pins the gap at 2px and draws
            # the icon in the theme color; we build the content ourselves so
            # the icon takes the text color and the gap opens up.
            send_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            send_box.set_halign(Gtk.Align.CENTER)
            icon = Gtk.Image.new_from_icon_name("mail-send-symbolic",
                                                Gtk.IconSize.BUTTON)
            icon.get_style_context().add_class("jd-sendicon")
            send_box.pack_start(icon, False, False, 0)
            self.send_lbl = Gtk.Label(label=_("SEND NEXT TASK") if direct
                                      else _("QUEUE NEXT TASK"))
            send_box.pack_start(self.send_lbl, False, False, 0)
            self.send_btn = Gtk.Button()
            self.send_btn.add(send_box)
            self.send_btn.get_style_context().add_class("jd-send")
            if sess["target"] == INBOX:
                self.send_lbl.set_text(_("SEND NEXT TASK"))
                self.send_btn.set_tooltip_text(
                    _("Inbox notes have no target. Move one to a session with ⇄."))
            self.send_btn.connect("clicked", lambda *_: self.app.send_next(self.key()))
            foot.pack_end(self.send_btn, False, False, 0)
            inner.pack_start(foot, False, False, 0)

        def on_more(self, btn):
            """Session actions, in a menu so they do not crowd the header."""
            menu = Gtk.Menu()
            k = self.key()
            items = [
                ("Bu oturuma not…", lambda: self.app.quick_note(
                    None if k == INBOX else k)),
                (_("Decision log"), lambda: open_in_editor(EVENTS_PATH)),
                (_("Queue file"), lambda: open_in_editor(QUEUE_MD)),
                ("Ayarlar…", self.app.open_settings),
            ]
            for label, cb in items:
                mi = Gtk.MenuItem.new_with_label(label)
                mi.connect("activate",
                           lambda _w, f=cb: GLib.idle_add(self.app._once(f)))
                menu.append(mi)
            menu.show_all()
            menu.popup_at_widget(btn, Gdk.Gravity.SOUTH_EAST,
                                 Gdk.Gravity.NORTH_EAST, None)

        def on_star(self, btn):
            btn.set_image(Gtk.Image.new_from_icon_name(
                "starred-symbolic" if btn.get_active() else "non-starred-symbolic",
                Gtk.IconSize.BUTTON))

        def sync_placeholder(self, *_):
            buf = self.tv.get_buffer()
            self.ph.set_visible(buf.get_char_count() == 0)

        def on_auto(self, _sw, state):
            sid = self.sess.get("session_id")
            if sid:
                Registry().upsert(sid, auto_advance=state, advance_count=0)
                AutoPrefs().set(self.sess.get("cwd"), state)
                self.set_auto_hint(state)
            return False

        def set_auto_hint(self, on):
            self.auto_hint.set_text(
                _("takes the next one at the end of each turn")
                if on else _("hands over nothing on its own"))

        def key(self):
            return self.sess["target"]

        def apply_session(self, sess):
            """Refresh the session facts and rewrite the visible labels.

            The page is built once, but the session name changes later: Claude
            Code produces its title a few turns in. This used to update only
            self.sess, leaving the Gtk.Labels on the text they were built with
            — so the window stayed stuck on the folder name while the tray
            menu, rebuilt from scratch on every open, showed the new one.
            """
            self.sess = sess
            self.title_lbl.set_text((sess.get("label") or "?").upper())
            self.build_chips(sess)
            if self.path_lbl is not None:
                self.path_lbl.set_text(sess.get("cwd") or "")
            ctx = self.get_style_context()
            if sess.get("live"):
                ctx.remove_class("jd-dead")
            else:
                ctx.add_class("jd-dead")

        def build_chips(self, sess):
            """Spread the identity details across chips.

            session_line gave the same facts as one line, and telling the
            parts apart meant counting '·' separators.
            """
            for ch in self.chips.get_children():
                self.chips.remove(ch)
            items = []
            folder = session_folder(sess)
            if folder and folder != sess.get("label"):
                items.append(folder)
            target = sess.get("target") or ""
            if target:
                items.append(target if sess.get("live")
                             else "%s · " % target + _("closed"))
            csrc = sess.get("color_source")
            if csrc and csrc not in ("palet", "config"):
                items.append("tema: %s" % csrc)
            for text in items:
                lbl = Gtk.Label(label=text, xalign=0)
                lbl.get_style_context().add_class("jd-chip")
                lbl.set_ellipsize(Pango.EllipsizeMode.END)
                lbl.set_max_width_chars(22)
                self.chips.pack_start(lbl, False, False, 0)
            self.chips.show_all()

        def on_tv_key(self, _w, ev):
            ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
            shift = ev.state & Gdk.ModifierType.SHIFT_MASK
            if ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                if shift:
                    return False
                self.add_note(bool(ctrl))
                return True
            return False

        def add_note(self, send):
            buf = self.tv.get_buffer()
            s, e = buf.get_bounds()
            text = buf.get_text(s, e, True).strip()
            if not text:
                return
            tgt = None if self.sess["target"] == INBOX else self.sess["target"]
            task = store.add(text, target=tgt, project=self.sess["label"],
                             priority=1 if self.star.get_active() else 0)
            buf.set_text("")
            self.star.set_active(False)
            self.app.request_refresh()
            if send and task:
                self.app.send_task(task["id"])

        def refresh(self):
            k = self.key()
            fresh = next((s for s in self.app.sessions if s["target"] == k), None)
            if fresh:
                self.sess = fresh
            state = self.sess.get("state", "unknown")
            self.state_lbl.set_text(state_word(self.sess))
            self.state_dot.set_visible(bool(state_word(self.sess)))
            self.app.update_tab_mark(self.sess)

            n_pending = len(store.pending(k))
            auto_on = bool(self.sess.get("auto_advance"))
            # While the queue waits, the last decision shows here — so "why
            # didn't it come?" is answered without opening the log.
            blocked = last_block_reason(k) if n_pending and k != INBOX else None
            if state == "asking" and k != INBOX:
                self.notice.set_text(
                    _("Claude asked a question. Sending a task would answer it on "
                      "your behalf — answer it first and the lock lifts."))
                self.notice.show()
            elif blocked:
                self.notice.set_text(blocked)
                self.notice.show()
            elif n_pending and not is_tmux_target(k) and k != INBOX:
                if auto_on:
                    self.notice.set_text(
                        _("auto is on — Claude takes the next task at the end of "
                          "every turn."))
                else:
                    self.notice.set_text(
                        _("This session is not in tmux: ccdo hands over nothing on "
                          "its own. Type /next in it, or switch 'auto' on."))
                self.notice.show()
            else:
                self.notice.hide()
            if self.sess.get("session_id"):
                on = bool(self.sess.get("auto_advance"))
                self.auto.handler_block(self.auto_handler)
                self.auto.set_active(on)
                self.auto.set_state(on)
                self.auto.handler_unblock(self.auto_handler)
                self.auto.set_sensitive(True)
                self.set_auto_hint(on)
            else:
                self.auto.set_sensitive(False)
                self.auto_hint.set_text(_("no auto on this tab"))

            tasks = [t for t in store.all()
                     if t.get("status") != "done"
                     and ((k == INBOX and not t.get("target")) or t.get("target") == k)]
            tasks.sort(key=lambda t: (t.get("status") == "sent", -int(t.get("priority", 0))))
            for ch in self.listbox.get_children():
                self.listbox.remove(ch)
            if not tasks:
                row = Gtk.ListBoxRow()
                lab = Gtk.Label(label=_("queue is empty"), xalign=0)
                lab.get_style_context().add_class("jd-empty")
                lab.set_margin_top(8)
                lab.set_margin_bottom(8)
                lab.set_margin_start(4)
                row.add(lab)
                self.listbox.add(row)
            pending_ids = [t["id"] for t in tasks if t.get("status") == "pending"]
            for t in tasks:
                n = (pending_ids.index(t["id"]) + 1
                     if t["id"] in pending_ids else None)
                self.listbox.add(self.make_row(t, n, len(pending_ids)))
            has_pending = any(t.get("status") == "pending" for t in tasks)
            st = self.sess.get("state")
            # "asking": Claude asked a question. Sending a task would answer
            # it on the user's behalf — both delivery routes stay locked.
            blocked = st in ("ended", "asking")
            if is_tmux_target(self.key()):
                blocked = blocked or st == "waiting"
            self.send_btn.set_sensitive(
                has_pending and bool(self.sess.get("live")) and not blocked)
            self.listbox.show_all()

            n_hist = len(history_for_target(k))
            self.hist_exp.set_label(_("History (%d)") % n_hist if n_hist else _("History"))
            if self.hist_exp.get_expanded():
                self.refresh_history()

        def on_hist_toggle(self, *_):
            if self.hist_exp.get_expanded():
                self.refresh_history()

        def refresh_history(self):
            recs = history_for_target(self.key(), limit=HISTORY_UI_LIMIT)
            for ch in self.hist_box.get_children():
                self.hist_box.remove(ch)
            if not recs:
                row = Gtk.ListBoxRow()
                lab = Gtk.Label(label=_("history is empty"), xalign=0)
                lab.get_style_context().add_class("jd-empty")
                lab.set_margin_top(8)
                lab.set_margin_bottom(8)
                lab.set_margin_start(4)
                row.add(lab)
                self.hist_box.add(row)
            for rec in recs:
                self.hist_box.add(self.make_history_row(rec))
            self.hist_box.show_all()

        def make_history_row(self, rec):
            t = rec.get("task") or {}
            text = (t.get("text") or "").strip()
            first = text.splitlines()[0] if text else ""

            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_border_width(4)

            glyph = Gtk.Label(label=EVENT_GLYPH.get(rec.get("event"), "·"),
                              xalign=0.5)
            glyph.set_width_chars(2)
            glyph.get_style_context().add_class("jd-sub")
            box.pack_start(glyph, False, False, 0)

            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            lab = Gtk.Label(label=first, xalign=0)
            lab.set_ellipsize(Pango.EllipsizeMode.END)
            lab.set_max_width_chars(34)
            lab.set_width_chars(10)
            col.pack_start(lab, False, False, 0)
            stamp = (rec.get("ts") or "").replace("T", " ")[:16]
            meta = Gtk.Label(label="%s · %s" % (stamp, t.get("id", "?")), xalign=0)
            meta.get_style_context().add_class("jd-sub")
            col.pack_start(meta, False, False, 0)
            box.pack_start(col, True, True, 0)

            row.add(box)
            # A multi-line note will not fit on the row; the tooltip has it.
            if text:
                row.set_tooltip_text(text)
            return row

        def make_row(self, t, order=None, total=0):
            row = Gtk.ListBoxRow()
            row.get_style_context().add_class("jd-taskcard")
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            box.set_border_width(6)

            # Position: the next task is always number 1
            num = Gtk.Label(label=("%d" % order) if order else "·", xalign=0.5)
            num.get_style_context().add_class("jd-num" if order != 1 else "jd-num-next")
            num.set_size_request(20, -1)
            num.set_valign(Gtk.Align.START)
            box.pack_start(num, False, False, 0)

            # Move up / move down
            if order:
                arrows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                for glyph, delta, tip in (("▲", -1, _("Move up")),
                                          ("▼", +1, _("Move down"))):
                    b = Gtk.Button(label=glyph)
                    b.set_relief(Gtk.ReliefStyle.NONE)
                    b.set_tooltip_text(tip)
                    b.get_style_context().add_class("jd-arrow")
                    b.set_sensitive(not (delta < 0 and order == 1)
                                    and not (delta > 0 and order == total))
                    b.connect("clicked", lambda _w, i=t["id"], d=delta:
                              (store.reorder(i, d), self.app.request_refresh()))
                    arrows.pack_start(b, True, True, 0)
                box.pack_start(arrows, False, False, 0)

            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            head = t["text"].strip().splitlines()[0]
            if int(t.get("priority", 0)) > 0:
                head = "★ " + head
            lab = Gtk.Label(label=head, xalign=0)
            lab.set_ellipsize(Pango.EllipsizeMode.END)
            lab.set_max_width_chars(28)
            lab.set_width_chars(10)
            lab.set_tooltip_text(t["text"])
            lab.get_style_context().add_class(
                "jd-task-sent" if t.get("status") == "sent" else "jd-task")
            extra = " · " + _("sent") if t.get("status") == "sent" else ""
            meta = Gtk.Label(label="%s%s" % (t["id"], extra), xalign=0)
            meta.get_style_context().add_class("jd-meta")
            col.pack_start(lab, False, False, 0)
            col.pack_start(meta, False, False, 0)
            ev = Gtk.EventBox()
            ev.add(col)
            ev.connect("button-press-event",
                       lambda _w, e, i=t["id"]:
                       self.app.edit_task(i) if e.type == Gdk.EventType._2BUTTON_PRESS else None)
            box.pack_start(ev, True, True, 0)

            def mk(label, tip, cb):
                b = Gtk.Button(label=text_glyph(label))
                b.set_relief(Gtk.ReliefStyle.NONE)
                b.set_tooltip_text(tip)
                b.get_style_context().add_class("jd-rowbtn")
                b.connect("clicked", cb)
                return b

            box.pack_end(mk("✕", _("Delete"),
                            lambda *_: (store.delete(t["id"]), self.app.request_refresh())),
                         False, False, 0)
            box.pack_end(mk("✓", _("Done"),
                            lambda *_: (store.update(t["id"], status="done"),
                                        self.app.request_refresh())),
                         False, False, 0)
            box.pack_end(mk("✎", _("Edit (text, session, star)"),
                            lambda *_: self.app.edit_task(t["id"])),
                         False, False, 0)
            box.pack_end(mk("▶", _("Send"), lambda *_: self.app.send_task(t["id"])),
                         False, False, 0)
            row.add(box)
            return row

    # ------------------------------------------------------------------ #


    class EditDialog(Gtk.Dialog):
        """Edit a queued task: its text, target session and star."""

        def __init__(self, parent, app, task):
            super().__init__(title=_("Edit task"), transient_for=parent,
                             modal=True, destroy_with_parent=True)
            add_headerbar(self, _("Edit task"))
            self.app = app
            self.task = task
            self.set_default_size(460, 320)
            self.get_style_context().add_class("jd-window")
            mark_body(self)

            box = self.get_content_area()
            box.set_spacing(8)
            box.set_border_width(14)

            self.tv = Gtk.TextView()
            self.tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self.tv.get_style_context().add_class("jd-input")
            self.tv.get_buffer().set_text(task["text"])
            self.tv.connect("key-press-event", self.on_key)
            attach_image_paste(self.tv)
            attach_file_drop(self.tv)
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sw.set_size_request(-1, 170)
            sw.add(self.tv)
            box.pack_start(sw, True, True, 0)

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lbl = Gtk.Label(label=_("Session:"), xalign=0)
            lbl.get_style_context().add_class("jd-sub")
            row.pack_start(lbl, False, False, 0)

            self.combo = Gtk.ComboBoxText()
            self.targets = []
            for sess in app.sessions:
                self.targets.append(None if sess["target"] == INBOX else sess["target"])
                self.combo.append_text("%s  (%s)" % (sess["label"], sess["target"]))
            cur = task.get("target")
            try:
                self.combo.set_active(self.targets.index(cur))
            except ValueError:
                self.combo.append_text("%s  (%s)" % (cur or "?", _("closed")))
                self.targets.append(cur)
                self.combo.set_active(len(self.targets) - 1)
            row.pack_start(self.combo, True, True, 0)

            self.star = Gtk.ToggleButton(label="★")
            self.star.get_style_context().add_class("jd-star")
            self.star.set_tooltip_text(_("Star (does not change the order)"))
            self.star.set_active(int(task.get("priority", 0)) > 0)
            row.pack_end(self.star, False, False, 0)
            box.pack_start(row, False, False, 0)

            hint = Gtk.Label(label=_("Ctrl+Enter save · Ctrl+V image · Esc cancel"), xalign=0)
            hint.get_style_context().add_class("jd-hint")
            box.pack_start(hint, False, False, 0)

            self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
            save = self.add_button(_("Save"), Gtk.ResponseType.OK)
            save.get_style_context().add_class("suggested-action")
            self.set_default_response(Gtk.ResponseType.OK)
            self.show_all()
            self.tv.grab_focus()

        def on_key(self, _w, ev):
            ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
            if ctrl and ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                self.response(Gtk.ResponseType.OK)
                return True
            return False

        def result(self):
            buf = self.tv.get_buffer()
            a, b = buf.get_bounds()
            idx = self.combo.get_active()
            return {
                "text": buf.get_text(a, b, True).strip(),
                "target": self.targets[idx] if 0 <= idx < len(self.targets) else self.task.get("target"),
                "priority": 1 if self.star.get_active() else 0,
            }


    class SettingsDialog(Gtk.Dialog):
        """Ayarlar penceresi — SETTINGS_SCHEMA'dan uretilir.

        Listeler (process_match, question_patterns, sessions) burada yok:
        onlar dosyadan duzenleniyor, alttaki buton dosyayi aciyor.
        """

        def __init__(self, parent, cfg):
            super().__init__(title=_("ccdo — settings"), transient_for=parent,
                             modal=True, destroy_with_parent=True)
            add_headerbar(self, _("ccdo — settings"))
            self.set_default_size(500, 560)
            self.get_style_context().add_class("jd-window")
            mark_body(self)
            self.widgets = {}

            outer = self.get_content_area()
            outer.set_spacing(0)
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            # Padding via margins rather than border_width: inside a
            # ScrolledWindow, border_width clipped the first letter.
            for setter in ("set_margin_start", "set_margin_end",
                           "set_margin_top", "set_margin_bottom"):
                getattr(box, setter)(16)
            sw.add(box)
            outer.pack_start(sw, True, True, 0)

            for section, fields in SETTINGS_SCHEMA:
                head = Gtk.Label(label=_(section).upper(), xalign=0)
                head.get_style_context().add_class("jd-section")
                head.set_margin_top(16)
                head.set_margin_bottom(6)
                head.set_margin_start(2)
                box.pack_start(head, False, False, 0)

                card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                card.get_style_context().add_class("jd-card")
                box.pack_start(card, False, False, 0)

                grid = Gtk.Grid(column_spacing=14, row_spacing=12)
                card.pack_start(grid, False, False, 0)
                for row, spec in enumerate(fields):
                    key, kind, label, tip = spec[:4]
                    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                    left.set_hexpand(True)
                    lbl = Gtk.Label(label=_(label), xalign=0)
                    lbl.set_line_wrap(True)
                    lbl.set_max_width_chars(40)
                    left.pack_start(lbl, False, False, 0)
                    if tip:
                        sub = Gtk.Label(label=_(tip), xalign=0)
                        sub.get_style_context().add_class("jd-hint")
                        sub.set_line_wrap(True)
                        sub.set_max_width_chars(46)
                        left.pack_start(sub, False, False, 0)
                    grid.attach(left, 0, row, 1, 1)

                    w = self._widget(kind, cfg.get(key), spec)
                    w.set_halign(Gtk.Align.END)
                    w.set_valign(Gtk.Align.CENTER)
                    grid.attach(w, 1, row, 1, 1)
                    self.widgets[key] = (kind, w)

            note = Gtk.Label(
                label=_("List-valued settings (process_match, question_patterns, "
                        "sessions) are edited in the file."), xalign=0)
            note.get_style_context().add_class("jd-hint")
            note.set_line_wrap(True)
            note.set_margin_top(16)
            box.pack_start(note, False, False, 0)

            raw = Gtk.Button(label=_("Open the settings file"))
            raw.set_halign(Gtk.Align.START)
            raw.connect("clicked", lambda *_: open_in_editor(CONFIG_PATH))
            box.pack_start(raw, False, False, 0)

            # The version sits outside the scrolled area: inside it, you had to
            # scroll to the very bottom to find out what you were running.
            latest = read_update_cache().get("latest", "")
            ver = Gtk.Label(xalign=0, label=(
                _("ccdo %s  ·  new version available: %s") % (VERSION, latest)
                if newer_version(latest) else "ccdo %s" % VERSION))
            ver.get_style_context().add_class("jd-hint")
            ver.set_margin_start(16)
            ver.set_margin_end(16)
            ver.set_margin_top(8)
            ver.set_margin_bottom(4)
            outer.pack_start(ver, False, False, 0)

            self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
            self.add_button(_("Save"), Gtk.ResponseType.OK).get_style_context(
                ).add_class("suggested-action")
            self.set_default_response(Gtk.ResponseType.OK)
            self.show_all()

        def _widget(self, kind, value, spec):
            if kind == "bool":
                w = Gtk.Switch()
                w.set_active(bool(value))
                return w
            if kind in ("int", "float"):
                lo, hi = spec[4], spec[5]
                step = 1 if kind == "int" else 0.05
                w = Gtk.SpinButton.new_with_range(lo, hi, step)
                if kind == "float":
                    w.set_digits(2)
                w.set_value(float(value if value is not None else lo))
                return w
            if kind in ("choice", "lang"):
                opts = (["auto"] + available_languages() if kind == "lang"
                        else list(spec[4]))
                w = Gtk.ComboBoxText()
                for opt in opts:
                    w.append_text(opt)
                try:
                    w.set_active(opts.index(value))
                except ValueError:
                    w.set_active(0)
                return w
            w = Gtk.Entry()
            w.set_text("" if value is None else str(value))
            w.set_width_chars(12)
            w.set_max_width_chars(12)
            return w

        def values(self):
            out = {}
            for key, (kind, w) in self.widgets.items():
                if kind == "bool":
                    out[key] = w.get_active()
                elif kind == "int":
                    out[key] = int(w.get_value())
                elif kind == "float":
                    out[key] = round(float(w.get_value()), 2)
                elif kind in ("choice", "lang"):
                    out[key] = w.get_active_text()
                else:
                    out[key] = w.get_text()
            return out


    class QuickNoteDialog(Gtk.Dialog):
        """A small note box opened from the tray menu.

        A text entry cannot be embedded in the menu itself: AppIndicator
        exports the menu over DBus (com.canonical.dbusmenu), and that protocol
        carries labels and marks only, never embedded widgets. So a menu item
        opens the box instead; the type-and-Enter flow stays as quick.
        """

        def __init__(self, app, target=None):
            super().__init__(title=_("ccdo — quick note"), modal=True)
            add_headerbar(self, _("ccdo — quick note"))
            self.app = app
            self.set_default_size(420, 190)
            if not IS_MAC:                      # see NoteWindow: the menu bar
                self.set_keep_above(True)
            self.set_position(Gtk.WindowPosition.MOUSE)
            self.get_style_context().add_class("jd-window")
            mark_body(self)

            box = self.get_content_area()
            box.set_spacing(8)
            box.set_border_width(14)

            self.tv = Gtk.TextView()
            self.tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self.tv.get_style_context().add_class("jd-input")
            self.tv.connect("key-press-event", self.on_key)
            attach_image_paste(self.tv)
            attach_file_drop(self.tv)
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sw.set_size_request(-1, 92)
            sw.add(self.tv)
            box.pack_start(sw, True, True, 0)

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lbl = Gtk.Label(label=_("Session:"), xalign=0)
            lbl.get_style_context().add_class("jd-sub")
            row.pack_start(lbl, False, False, 0)
            self.combo = Gtk.ComboBoxText()
            self.targets = []
            for sess in app.sessions:
                self.targets.append(None if sess["target"] == INBOX else sess["target"])
                self.combo.append_text("%s  (%s)" % (sess["label"], sess["target"]))
            try:
                self.combo.set_active(self.targets.index(target))
            except ValueError:
                self.combo.set_active(0 if self.targets else -1)
            row.pack_start(self.combo, True, True, 0)
            self.star = Gtk.ToggleButton(label="★")
            self.star.get_style_context().add_class("jd-star")
            self.star.set_tooltip_text(_("Starred"))
            row.pack_end(self.star, False, False, 0)
            box.pack_start(row, False, False, 0)

            hint = Gtk.Label(label=_("Enter add · Ctrl+Enter add+send · "
                                     "Shift+Enter newline · Ctrl+V image · Esc cancel"),
                             xalign=0)
            hint.get_style_context().add_class("jd-hint")
            box.pack_start(hint, False, False, 0)

            self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
            self.add_button(_("Add"), Gtk.ResponseType.OK).get_style_context(
                ).add_class("suggested-action")
            self.show_all()
            self.tv.grab_focus()

        def on_key(self, _w, ev):
            if ev.keyval not in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                return False
            if ev.state & Gdk.ModifierType.SHIFT_MASK:
                return False
            self.send_after = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
            self.response(Gtk.ResponseType.OK)
            return True

        send_after = False

        def result(self):
            buf = self.tv.get_buffer()
            a, b = buf.get_bounds()
            idx = self.combo.get_active()
            return {
                "text": buf.get_text(a, b, True).strip(),
                "target": self.targets[idx] if 0 <= idx < len(self.targets) else None,
                "priority": 1 if self.star.get_active() else 0,
                "send": self.send_after,
            }


    class NoteWindow(Gtk.Window):
        def __init__(self, app):
            super().__init__(title="ccdo")
            self.app = app
            self.set_default_size(560, 660)
            self.set_skip_taskbar_hint(True)
            # keep_above + UTILITY starts a focus fight on some window
            # managers; let the config turn either off. On macOS it also
            # floats over the auto-hiding menu bar and keeps it from settling,
            # so it is off there whatever the setting says.
            if cfg.get("window_keep_above", True) and not IS_MAC:
                self.set_keep_above(True)
            if cfg.get("window_utility_hint", False):
                self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
            self.get_style_context().add_class("jd-window")
            # Without a HeaderBar the title was drawn by mutter's plain frame;
            # with CSD we get the desktop's own close/minimise/maximise
            # buttons, laid out per the user's button-layout setting.
            head = Gtk.HeaderBar()
            head.set_show_close_button(True)
            head.set_title("ccdo")
            head.set_has_subtitle(False)
            self.set_titlebar(head)
            self.connect("delete-event", self.on_delete)
            self.connect("key-press-event", self.on_key)
            self.nb = Gtk.Notebook()
            self.nb.set_scrollable(True)
            self.nb.get_style_context().add_class("jd-body")
            self.add(self.nb)

        def on_delete(self, *_):
            self.hide()
            return True

        def on_key(self, _w, ev):
            ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
            if ev.keyval == Gdk.KEY_Escape:
                self.hide()
                return True
            if ctrl and ev.keyval in (Gdk.KEY_Tab, Gdk.KEY_Page_Down):
                self.nb.next_page()
                return True
            if ctrl and ev.keyval == Gdk.KEY_Page_Up:
                self.nb.prev_page()
                return True
            if ctrl and Gdk.KEY_1 <= ev.keyval <= Gdk.KEY_9:
                idx = ev.keyval - Gdk.KEY_1
                if idx < self.nb.get_n_pages():
                    self.nb.set_current_page(idx)
                return True
            return False

    # ------------------------------------------------------------------ #

    class App:
        def __init__(self):
            self.buffers = {}
            self.pages = {}
            self.tab_labels = {}
            self.tab_marks = {}
            self.sessions = []
            self.win = NoteWindow(self)
            self.win.nb.connect("switch-page",
                                lambda *_: GLib.idle_add(self.sync_tab_accent))
            self.menu = Gtk.Menu()
            self.last_mtime = None
            self.last_sig = None
            self._refresh_pending = False
            self._menu_dirty = False
            self._menu_sig = None
            self._last_label = None
            self._positioned = False
            self._last_discover = 0.0
            self._discover_pending = False
            self.menu.connect("hide", self._on_menu_hidden)

            if use_statusicon:
                self.tray = Gtk.StatusIcon()
                self.tray.set_from_file(icon_path)
                self.tray.connect("activate", lambda *_: self.toggle_window())
                self.tray.connect("popup-menu", self.on_popup)
                self.ind = None
            else:
                self.ind = Indicator.Indicator.new(
                    APP_NAME, "ccdo", Indicator.IndicatorCategory.APPLICATION_STATUS)
                self.ind.set_icon_theme_path(ICON_DIR)
                self.ind.set_icon("ccdo")
                self.ind.set_status(Indicator.IndicatorStatus.ACTIVE)
                self.ind.set_title("ccdo")
                self.ind.set_menu(self.menu)
                self.tray = None

            IPCServer(self.on_ipc).start()
            self.discover()
            self.start_update_check()
            # And keep looking. Checking only at startup meant a tray left
            # running for days never noticed a release — you had to restart it
            # to be told. check_update rate-limits itself to once a day, so
            # asking hourly costs nothing but a cache read.
            GLib.timeout_add_seconds(3600, self._recheck_updates)
            GLib.timeout_add_seconds(2, self.poll_store)
            GLib.timeout_add_seconds(max(2, int(cfg.get("discover_interval", 4))),
                                     self.poll_sessions)

        # -- keep typed text alive across a tab rebuild ----------------- #

        def buffer_for(self, target):
            if target not in self.buffers:
                self.buffers[target] = Gtk.TextBuffer()
            return self.buffers[target]

        # -- discovery -------------------------------------------------- #

        def discover(self, force=False):
            now = time.monotonic()
            if not force and (now - self._last_discover) < 0.5:
                # Do not drop the request: retry once the rate limit clears.
                if not self._discover_pending:
                    self._discover_pending = True
                    GLib.timeout_add(500, self._retry_discover)
                if DEBUG:
                    sys.stderr.write("[ccdo] scan deferred (rate limit)\n")
                return None
            self._last_discover = now
            live = discover_sessions(cfg)
            live_targets = {s["target"] for s in live}
            sessions = list(live)
            for t in store.active_targets():
                if t not in live_targets:
                    sessions.append(ghost_session(cfg, t))
            sessions.append({"target": INBOX, "label": "ideabox", "color": "#8a8f99",
                             "cwd": "", "cmd": "", "queue_file": None, "live": True,
                             "color_source": "palet"})
            self.sessions = sessions
            rebuild_accent_css(sessions)

            # The signature is the tab's IDENTITY only: color and state must
            # stay out, or the tabs get rebuilt on every state change.
            sig = tuple((s["target"], s["label"], s["live"]) for s in sessions)
            if sig != self.last_sig:
                if DEBUG:
                    sys.stderr.write("[ccdo] rebuilding tabs: %r\n" % (sig,))
                self.last_sig = sig
                self.rebuild_pages()
            elif DEBUG:
                sys.stderr.write("[ccdo] scan: no change (%d sessions)\n" % len(sessions))
            self.request_refresh()
            # DIKKAT: burada True DONME. GLib bunu "call me again" diye
            # yorumlar; idle kaynagi olarak baglandiginda sonsuz donguye girer.
            return None

        def _retry_discover(self):
            self._discover_pending = False
            self.discover(force=True)
            return False          # tek seferlik

        def poll_sessions(self):
            try:
                self.discover()
            except Exception as e:
                sys.stderr.write("[ccdo] scan error: %s\n" % e)
            return True

        def poll_store(self):
            try:
                m = store.fingerprint()
                if m != self.last_mtime:
                    if DEBUG:
                        sys.stderr.write("[ccdo] %.3f queue changed %r -> %r\n"
                                         % (time.time(), self.last_mtime, m))
                    self.last_mtime = m
                    self.request_refresh()
            except Exception as e:
                sys.stderr.write("[ccdo] poll error: %s\n" % e)
            return True

        def rebuild_pages(self):
            """Add and remove only the tabs that changed.

            Every page used to be torn down and rebuilt; with the whole window
            collapsing on each signature change, it flickered and lost focus.
            Existing pages now stay where they are.
            """
            nb = self.win.nb
            wanted = [s["target"] for s in self.sessions]
            current = nb.get_current_page()
            current_target = None
            if current is not None and 0 <= current < nb.get_n_pages():
                page = nb.get_nth_page(current)
                if isinstance(page, SessionPage):
                    current_target = page.key()

            # Kalkanlari cikar
            for target in list(self.pages):
                if target not in wanted:
                    page = self.pages.pop(target)
                    self.tab_labels.pop(target, None)
                    self.tab_marks.pop(target, None)
                    idx = nb.page_num(page)
                    if idx >= 0:
                        nb.remove_page(idx)

            # Add new ones, keep the order
            for i, s in enumerate(self.sessions):
                target = s["target"]
                page = self.pages.get(target)
                if page is None:
                    page = SessionPage(self, s)
                    self.pages[target] = page
                    nb.insert_page(page, self.make_tab(s), i)
                    # So tabs can be dragged into a different order. To keep a
                    # hand-made order intact, rebuild_pages never moves an
                    # existing page; it only appends new ones.
                    nb.set_tab_reorderable(page, True)
                    page.show_all()
                else:
                    page.apply_session(s)
                    self.update_tab(s)
                    if nb.page_num(page) != i:
                        nb.reorder_child(page, i)

            if current_target and current_target in self.pages:
                idx = nb.page_num(self.pages[current_target])
                if idx >= 0:
                    nb.set_current_page(idx)
            self.sync_tab_accent()

        def sync_tab_accent(self, *_):
            """Pull the selected tab's underline to that session's color.

            A class cannot be put on the tab node (CSS has no way up to a
            parent), so it sits on the Notebook and changes as the page does.
            """
            nb = self.win.nb
            ctx = nb.get_style_context()
            for cls in list(ctx.list_classes()):
                if cls.startswith("jd-nb-"):
                    ctx.remove_class(cls)
            idx = nb.get_current_page()
            page = nb.get_nth_page(idx) if idx >= 0 else None
            for target, p in self.pages.items():
                if p is page:
                    ctx.add_class("jd-nb-%s" % slug(target))
                    break

        def make_tab(self, s):
            tab = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            tab.get_style_context().add_class("jd-a-%s" % slug(s["target"]))
            # The state mark sits left of the name so a glance at the tab
            # shows which session asked something or finished. A symbolic icon
            # rather than a text glyph: clearer on a tab and always one color.
            mark = Gtk.Image.new_from_icon_name(state_icon(s) or None,
                                                Gtk.IconSize.MENU)
            mark.set_valign(Gtk.Align.CENTER)
            mark.get_style_context().add_class("jd-tabicon")
            tab.pack_start(mark, False, False, 0)
            lbl = Gtk.Label(label=session_tab_text(s))
            lbl.set_tooltip_text(session_tooltip(s))
            tab.pack_start(lbl, False, False, 0)
            # Kept so the label can be refreshed later: the session name can
            # change after the tab is first built.
            self.tab_labels[s["target"]] = lbl
            self.tab_marks[s["target"]] = mark

            # A Gtk.Box has no window of its own and cannot receive scroll
            # events. An invisible EventBox wraps it so scrolling changes tabs
            # ONLY over the tab strip, not in the note box or the list.
            eb = Gtk.EventBox()
            eb.set_visible_window(False)
            eb.add_events(Gdk.EventMask.SCROLL_MASK
                          | Gdk.EventMask.SMOOTH_SCROLL_MASK)
            eb.connect("scroll-event", self.on_tab_scroll)
            eb.add(tab)
            eb.show_all()
            return eb

        def on_tab_scroll(self, _w, ev):
            names = {Gdk.ScrollDirection.UP: "up",
                     Gdk.ScrollDirection.DOWN: "down",
                     Gdk.ScrollDirection.LEFT: "left",
                     Gdk.ScrollDirection.RIGHT: "right",
                     Gdk.ScrollDirection.SMOOTH: "smooth"}
            __, dx, dy = ev.get_scroll_deltas()
            step = scroll_step(names.get(ev.direction, ""), dx, dy)
            if not step:
                return False
            nb = self.win.nb
            n = nb.get_n_pages()
            if n < 2:
                return True
            # Uclarda durmak yerine basa/sona sar: az sekmede daha rahat.
            nb.set_current_page((nb.get_current_page() + step) % n)
            return True

        def update_tab_mark(self, sess):
            """Refresh the state mark on a tab.

            Tabs are rebuilt only when the signature (target/name/liveness)
            changes, and state is not part of it — so the mark is updated from
            here on every refresh.
            """
            mark = self.tab_marks.get(sess.get("target"))
            if mark is None:
                return
            name = state_icon(sess) or None
            if mark.get_icon_name()[0] != name:
                mark.set_from_icon_name(name, Gtk.IconSize.MENU)
            lbl = self.tab_labels.get(sess.get("target"))
            if lbl is not None:
                tip = session_tooltip(sess)
                words = state_text(sess)
                lbl.set_tooltip_text("%s — %s" % (tip, words) if words else tip)

        def update_tab(self, s):
            """Refresh an existing tab's label and tooltip."""
            lbl = self.tab_labels.get(s["target"])
            if lbl is None:
                return
            text = session_tab_text(s)
            if lbl.get_text() != text:
                lbl.set_text(text)
            lbl.set_tooltip_text(session_tooltip(s))

        # -- ipc -------------------------------------------------------- #

        @staticmethod
        def _once(fn, *a):
            """For GLib.idle_add: drop the source whatever the callback returns."""
            def wrapper():
                try:
                    fn(*a)
                except Exception as e:
                    sys.stderr.write("[ccdo] idle error: %s\n" % e)
                return False          # kaynagi kaldir, tekrarlama
            return wrapper

        def on_ipc(self, data):
            cmd = (data or "").strip()
            if cmd in ("show", "capture"):
                GLib.idle_add(self._once(self.show_window))
            elif cmd == "toggle":
                GLib.idle_add(self._once(self.toggle_window))
            elif cmd == "refresh":
                GLib.idle_add(self._once(self.request_refresh))
            elif cmd == "rediscover":
                GLib.idle_add(self._once(self.discover))
            elif cmd == "next":
                GLib.idle_add(self._once(self.send_next, None))
            return "ok"

        # -- window ----------------------------------------------------- #

        def show_window(self):
            self.win.show_all()
            self.win.present()
            if self._positioned:
                page = self.win.nb.get_nth_page(self.win.nb.get_current_page())
                if isinstance(page, SessionPage):
                    page.tv.grab_focus()
                return
            self._positioned = True
            try:
                disp = Gdk.Display.get_default()
                mon = disp.get_primary_monitor() or disp.get_monitor(0)
                geo = mon.get_workarea()
                w, _h = self.win.get_size()
                self.win.move(geo.x + geo.width - w - 16, geo.y + 16)
            except Exception:
                pass
            page = self.win.nb.get_nth_page(self.win.nb.get_current_page())
            if isinstance(page, SessionPage):
                page.tv.grab_focus()

        def toggle_window(self):
            if self.win.get_visible():
                self.win.hide()
            else:
                self.show_window()

        def on_popup(self, icon, button, t):
            self.menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, t)

        # -- actions ---------------------------------------------------- #

        def send_task(self, task_id):
            task = next((t for t in store.all() if t["id"] == task_id), None)
            if not task:
                return
            ok, msg = deliver(cfg, store, task)
            notify("ccdo: " + (_("sent") if ok else _("could not send")),
                   "%s\n%s" % (task["text"].splitlines()[0][:80], msg), cfg)
            self.request_refresh()

        def send_next(self, target=None):
            t = store.next_pending(target)
            if not t:
                notify("ccdo", _("No pending tasks."), cfg)
                return
            self.send_task(t["id"])

        def edit_task(self, task_id):
            task = next((t for t in store.all() if t["id"] == task_id), None)
            if not task:
                return
            dlg = EditDialog(self.parent_window(), self, task)
            if dlg.run() == Gtk.ResponseType.OK:
                res = dlg.result()
                if res["text"]:
                    store.update(task_id, text=res["text"], target=res["target"],
                                 priority=res["priority"])
                    self.request_refresh()
            dlg.destroy()

        def start_update_check(self):
            """Look for a new release in the background.

            On its own thread: network latency must not freeze the interface.
            The result is cached, and the menu shows it the next time it is
            built.
            """
            if not cfg.get("check_updates", True):
                return

            def work():
                try:
                    cache = check_update(cfg)
                except Exception:
                    return
                if newer_version(cache.get("latest", "")):
                    GLib.idle_add(self._once(self.rebuild_menu))

            threading.Thread(target=work, daemon=True).start()

        def _recheck_updates(self):
            self.start_update_check()
            return True                      # keep the timer alive

        def show_update(self):
            """The update window: what changed, and a button that does it.

            The notes are the ones GitHub published, cached alongside the tag,
            so opening this needs no network and no browser.
            """
            cache = read_update_cache()
            latest = cache.get("latest", "")
            dlg = Gtk.Dialog(title=_("Update"), transient_for=self.parent_window(),
                             modal=True)
            add_headerbar(dlg, _("Update"))
            dlg.get_style_context().add_class("jd-window")
            dlg.set_default_size(520, 460)
            mark_body(dlg)

            box = dlg.get_content_area()
            box.set_spacing(10)
            for setter in ("set_margin_start", "set_margin_end",
                           "set_margin_top", "set_margin_bottom"):
                getattr(box, setter)(16)

            head = Gtk.Label(xalign=0,
                             label=_("ccdo %s is out (you have %s)") % (latest, VERSION))
            head.get_style_context().add_class("jd-title")
            box.pack_start(head, False, False, 0)

            notes = Gtk.TextView()
            notes.set_editable(False)
            notes.set_cursor_visible(False)
            notes.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            notes.get_style_context().add_class("jd-input")
            notes.get_buffer().set_text(
                plain_markdown(cache.get("notes")) or _("No release notes."))
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sw.add(notes)
            box.pack_start(sw, True, True, 0)

            self.up_status = Gtk.Label(xalign=0, label="")
            self.up_status.get_style_context().add_class("jd-hint")
            self.up_status.set_line_wrap(True)
            box.pack_start(self.up_status, False, False, 0)

            link = Gtk.Button(label=_("Open on GitHub"))
            link.set_halign(Gtk.Align.START)
            link.connect("clicked",
                         lambda *_a: subprocess.Popen(["xdg-open", RELEASES_URL]))
            box.pack_start(link, False, False, 0)

            dlg.add_button(_("Close"), Gtk.ResponseType.CLOSE)
            self.up_btn = dlg.add_button(_("Update now"), Gtk.ResponseType.APPLY)
            self.up_btn.get_style_context().add_class("suggested-action")
            box.show_all()

            while True:
                resp = dlg.run()
                if resp != Gtk.ResponseType.APPLY:
                    break
                self.start_update()
            dlg.destroy()

        def start_update(self):
            """Run the installer without freezing the window.

            The work happens on a thread; only the reporting comes back to the
            main loop. Restarting is left to systemd — the process replacing
            its own binary cannot restart itself.
            """
            self.up_btn.set_sensitive(False)
            self.up_status.set_text(_("Updating…"))

            def done(rc, tail):
                if rc == 0:
                    self.up_status.set_text(_("Updated. Restarting…"))
                    notify("ccdo", _("Updated. Restarting…"), cfg)
                    GLib.timeout_add(900, self.restart_self)
                else:
                    self.up_btn.set_sensitive(True)
                    self.up_status.set_text(
                        _("Update failed: %s") % (tail.strip()[-160:] or rc))
                return False

            def work():
                try:
                    p = subprocess.run(update_command(), shell=True,
                                       capture_output=True, text=True, timeout=300)
                    rc, tail = p.returncode, (p.stderr or p.stdout or "")
                except Exception as e:
                    rc, tail = 1, str(e)
                GLib.idle_add(done, rc, tail)

            threading.Thread(target=work, daemon=True).start()

        def restart_self(self):
            if IS_MAC:
                rc, _out, _err = run_cmd(
                    ["launchctl", "kickstart", "-k",
                     "gui/%d/com.corevider.ccdo" % os.getuid()])
            else:
                rc, _out, _err = run_cmd(["systemctl", "--user", "restart", APP_NAME])
            if rc != 0:
                # Not running under systemd: the new binary is in place, but
                # only a restart picks it up, so quit and say so.
                notify("ccdo", _("Updated — start ccdo again to use it."), cfg)
                Gtk.main_quit()
            return False

        def parent_window(self):
            """The window to hang a dialog on, or None while it is hidden.

            A modal dialog transient for a window nobody can see leaves the
            user with no way back to it.
            """
            return self.win if self.win.get_visible() else None

        def open_settings(self):
            dlg = SettingsDialog(self.parent_window(), cfg)
            if dlg.run() == Gtk.ResponseType.OK:
                merged = dict(cfg)
                merged.update(dlg.values())
                save_config(merged)
                # cfg is updated in place: Store and the open windows hold the
                # same dict, and swapping it would leave them on the old
                # settings.
                cfg.clear()
                cfg.update(load_config())
                self.request_refresh()
            dlg.destroy()

        def quick_note(self, target=None):
            dlg = QuickNoteDialog(self, target)
            resp = dlg.run()
            res = dlg.result() if resp == Gtk.ResponseType.OK else None
            dlg.destroy()
            if not res or not res["text"]:
                return
            task = store.add(res["text"], target=res["target"],
                             project=None, priority=res["priority"])
            self.request_refresh()
            if task and res["send"]:
                self.send_task(task["id"])

        def move_menu(self, widget, task_id):
            m = Gtk.Menu()
            for s in self.sessions:
                if s["target"] == INBOX:
                    continue
                mi = Gtk.MenuItem.new_with_label("%s  (%s)" % (s["label"], s["target"]))
                mi.connect("activate", lambda _w, tg=s["target"]:
                           (store.update(task_id, target=tg), self.request_refresh()))
                m.append(mi)
            mi = Gtk.MenuItem.new_with_label(_("Move to the inbox"))
            mi.connect("activate", lambda _w: (store.update(task_id, target=None),
                                               self.request_refresh()))
            m.append(mi)
            m.show_all()
            m.popup_at_widget(widget, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

        # -- refresh ---------------------------------------------------- #

        def request_refresh(self, delay=200):
            """Tazeleme isteklerini tek cagriya indir.

            Hook'lardan ve zamanlayicilardan arka arkaya istek gelebiliyor;
            her birini ayri ayri islemek menuyu ve sekmeleri gereksiz yere
            yeniden kuruyordu.
            """
            if self._refresh_pending:
                return
            self._refresh_pending = True
            GLib.timeout_add(delay, self._flush_refresh)

        def _flush_refresh(self):
            self._refresh_pending = False
            try:
                self.refresh_all()
            except Exception as e:
                sys.stderr.write("[ccdo] refresh error: %s\n" % e)
            return False

        def refresh_all(self):
            if DEBUG:
                sys.stderr.write("[ccdo] %.3f refresh_all\n" % time.time())
            for p in self.pages.values():
                p.refresh()
            self.rebuild_menu()
            n = len(store.pending())
            label = str(n) if n else ""
            if self.ind is not None:
                if label != self._last_label:      # do not rewrite the same value
                    self._last_label = label
                    self.ind.set_label(label, "99")
            elif self.tray is not None:
                self.tray.set_tooltip_text(_("ccdo — %d waiting") % n)

        def menu_signature(self):
            """A digest of everything the menu shows."""
            parts = [read_update_cache().get("latest", "")]
            for sess in self.sessions:
                tasks = store.pending(sess["target"])
                if sess["target"] == INBOX and not tasks:
                    continue
                parts.append((sess["label"], sess["target"], bool(sess.get("live")),
                              len(tasks),
                              tuple((t["id"], t["text"].splitlines()[0][:45],
                                     int(t.get("priority", 0))) for t in tasks[:8])))
            return tuple(parts)

        def rebuild_menu(self):
            # The shell (GNOME Shell) draws the AppIndicator menu over DBus,
            # so on the GTK side it never looks "mapped" and we cannot tell
            # whether it is open. We therefore leave the menu alone unless its
            # CONTENT changed — that way an open dropdown does not snap shut.
            sig = self.menu_signature()
            if sig == self._menu_sig:
                if DEBUG:
                    sys.stderr.write("[ccdo] menu unchanged, left alone\n")
                return
            if DEBUG:
                sys.stderr.write("[ccdo] rebuilding the menu\n")
            self._menu_sig = sig
            self._menu_dirty = False
            self._build_menu()

        def _on_menu_hidden(self, *_):
            if self._menu_dirty:
                GLib.idle_add(self._once(self.rebuild_menu))

        def _build_menu(self):
            for ch in self.menu.get_children():
                self.menu.remove(ch)

            def item(label, cb=None, sensitive=True, menu=None):
                mi = Gtk.MenuItem.new_with_label(label)
                if cb:
                    # Run it after the menu has closed. A Gtk.Menu holds a
                    # pointer and keyboard grab while it is up; opening a
                    # modal dialog from inside the callback leaves that grab
                    # in place, and the window stops taking clicks and cannot
                    # be dragged. It only shows where GTK draws the menu
                    # itself — on Linux the shell draws it over DBus.
                    mi.connect("activate",
                               lambda *_, f=cb: GLib.idle_add(self._once(f)))
                mi.set_sensitive(sensitive)
                (menu or self.menu).append(mi)
                return mi

            latest = read_update_cache().get("latest", "")
            if newer_version(latest):
                item("⬆  " + _("Update available: %s") % latest, self.show_update)
                self.menu.append(Gtk.SeparatorMenuItem())

            item("➕  " + _("Quick note…"), lambda: self.quick_note(None))
            item("📝  " + _("Note window"), self.show_window)
            self.menu.append(Gtk.SeparatorMenuItem())

            shown = 0
            for s in self.sessions:
                tasks = store.pending(s["target"])
                if s["target"] == INBOX and not tasks:
                    continue
                shown += 1
                mark = "" if s.get("live") else "  (%s)" % _("closed")
                header = Gtk.MenuItem.new_with_label("%s — %d%s" % (s["label"], len(tasks), mark))
                sub = Gtk.Menu()
                header.set_submenu(sub)
                self.menu.append(header)
                if s.get("live") and s["target"] != INBOX:
                    item("➕  " + _("Note for this session…"),
                         lambda tg=s["target"]: self.quick_note(tg), True, sub)
                    item("▶  " + _("Send next task"),
                         lambda tg=s["target"]: self.send_next(tg), bool(tasks), sub)
                    sub.append(Gtk.SeparatorMenuItem())
                tasks.sort(key=lambda t: -int(t.get("priority", 0)))
                if not tasks:
                    item("(%s)" % _("empty"), None, False, sub)
                for t in tasks[:8]:
                    head = t["text"].strip().splitlines()[0]
                    head = head[:44] + "…" if len(head) > 45 else head
                    if int(t.get("priority", 0)) > 0:
                        head = "★ " + head
                    mi = Gtk.MenuItem.new_with_label(head)
                    act = Gtk.Menu()
                    for lbl, fn in ((_("Send"), lambda i=t["id"]: self.send_task(i)),
                                    (_("Done"), lambda i=t["id"]: (store.update(i, status="done"),
                                                                      self.request_refresh())),
                                    (_("Delete"), lambda i=t["id"]: (store.delete(i), self.request_refresh()))):
                        a = Gtk.MenuItem.new_with_label(lbl)
                        a.connect("activate", lambda _w, f=fn: f())
                        act.append(a)
                    mi.set_submenu(act)
                    sub.append(mi)

            if shown == 0:
                item("(%s)" % _("no live sessions"), None, False)

            self.menu.append(Gtk.SeparatorMenuItem())
            item(_("Scan sessions"), self.discover)
            item(_("Clear completed"), lambda: (store.purge_done(), self.request_refresh()))
            item(_("Queue file"), lambda: open_in_editor(QUEUE_MD))
            item(_("Decision log"), lambda: open_in_editor(EVENTS_PATH))
            item(_("Settings…"), self.open_settings)
            item(_("Quit"), Gtk.main_quit)
            self.menu.show_all()

    app_ref["app"] = App()
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.unlink(SOCK_PATH)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

def main(argv):
    # `ccdo list | head` gibi kullanimlarda boru kapaninca traceback basmasin
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass

    args = argv[1:]
    tray = (not args or args[0] in ("--tray", "--daemon", "--statusicon", "--gtk"))
    if tray:
        # On macOS the native menu bar app is the front end; GTK runs there but
        # never looks like it belongs. --gtk asks for the old one anyway.
        if IS_MAC and args[:1] != ["--gtk"] and start_mac_gui():
            return 0
        start_gui(args[:1] == ["--statusicon"])
        return 0

    cmd, rest = args[0], args[1:]
    cfg = load_config()
    load_language(cfg.get("language"))
    store = Store(cfg)

    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0

    if cmd == "add":
        target = project = None
        for flag in ("--target", "--project"):
            if flag in rest:
                i = rest.index(flag)
                val = rest[i + 1] if i + 1 < len(rest) else None
                rest = rest[:i] + rest[i + 2:]
                if flag == "--target":
                    target = val
                else:
                    project = val
        text = " ".join(rest).strip() or sys.stdin.read().strip()
        if target and ":" not in target:
            hit = next((s for s in discover_sessions(cfg)
                        if s["target"].split(":", 1)[0] == target
                        or s["label"].lower() == target.lower()), None)
            if hit:
                target = hit["target"]
        t = store.add(text, target=target, project=project)
        if t:
            ipc_send("refresh")
            print(t["id"])
            return 0
        sys.stderr.write("bos not\n")
        return 1

    if cmd in ("show", "capture", "toggle"):
        if ipc_send(cmd) is None:
            sys.stderr.write("the ccdo daemon is not running\n")
            return 1
        return 0

    if cmd == "list":
        for t in store.pending(rest[0] if rest else None):
            star = "*" if int(t.get("priority", 0)) > 0 else " "
            print("%s %s [%s] %s" % (star, t["id"], t.get("target") or "ideabox",
                                     t["text"].splitlines()[0]))
        return 0

    if cmd in ("next", "peek"):
        any_session = "--any" in rest
        rest = [r for r in rest if r != "--any"]
        if rest:
            target = rest[0]
        else:
            target = session_target_for_cwd(cfg)
            if target is None and not any_session:
                # The working directory matches no session. Limit this to
                # untargeted (inbox) tasks; otherwise the command could steal
                # a task from another session's queue.
                target = INBOX
        t = store.next_pending(target)
        if not t:
            print("")
            return 0
        print(t["text"])
        if cmd == "next":
            store.update(t["id"], status="sent", sent_at=now_iso(), push=False)
            ipc_send("refresh")
            sys.stderr.write("[ccdo] %s delivered\n" % t["id"])
        return 0

    # done/delete must not fail silently: they used to return 1 without
    # printing anything, so the only way to tell was to open the queue file.
    if cmd in ("done", "delete"):
        if not rest:
            sys.stderr.write("usage: ccdo %s <id>\n" % cmd)
            return 2
        tid = rest[0]
        ok = (store.update(tid, status="done") if cmd == "done"
              else store.delete(tid))
        ipc_send("refresh")
        if not ok:
            known = next((t for t in store.all() if t["id"] == tid), None)
            if known:
                sys.stderr.write("could not process the task: %s (status: %s)\n"
                                 % (tid, known.get("status")))
            else:
                sys.stderr.write("no such task: %s\n" % tid)
            return 1
        print("%s: %s" % (_("done") if cmd == "done" else _("deleted"), tid))
        return 0

    if cmd == "history":
        try:
            n = int(rest[0]) if rest else 20
        except ValueError:
            sys.stderr.write("usage: ccdo history [n]\n")
            return 2
        recs = read_history(limit=n)
        if not recs:
            print(_("the history is empty"))
            return 0
        for rec in reversed(recs):          # en yeni ustte
            t = rec["task"]
            first = (t.get("text") or "").strip().splitlines()
            print("%s %s  %s  %-8s %s" % (
                EVENT_GLYPH.get(rec.get("event"), "·"),
                (rec.get("ts") or "")[:19].replace("T", " "),
                t.get("id", "?"),
                (t.get("target") or t.get("project") or "ideabox")[:14],
                first[0] if first else ""))
        print("\ntamami: %s" % HISTORY_MD)
        return 0

    if cmd == "log":
        # ccdo log [n] [hedef]
        n, tgt = 30, None
        for arg in rest:
            if arg.isdigit():
                n = int(arg)
            else:
                tgt = arg
        recs = read_events(limit=n, target=tgt)
        if not recs:
            print("gunluk bos")
            return 0
        for rec in reversed(recs):          # en yeni ustte
            print("%s  %-14s %s" % (
                (rec.get("ts") or "")[:19].replace("T", " "),
                (rec.get("target") or "-")[:14],
                describe_event(rec)))
            if rec.get("task_text"):
                print("%s  %-14s   %s" % (" " * 19, "", rec["task_text"]))
        print("\ntamami: %s" % EVENTS_PATH)
        return 0

    if cmd == "send":
        force = "--force" in rest
        rest = [r for r in rest if r != "--force"]
        t = (next((x for x in store.all() if x["id"] == rest[0]), None) if rest
             else store.next_pending())
        if not t:
            sys.stderr.write("no task\n")
            return 1
        ok, msg = deliver(cfg, store, t, force=force)
        ipc_send("refresh")
        print(msg)
        return 0 if ok else 1

    if cmd == "hook":
        if not rest or rest[0] not in HOOK_HANDLERS:
            sys.stderr.write("usage: ccdo hook <%s>\n" % "|".join(HOOK_EVENTS))
            return 2
        return run_hook(cfg, store, rest[0])

    if cmd == "install-hooks":
        return install_hooks(dry_run="--dry-run" in rest)

    if cmd == "sessions":
        ss = discover_sessions(cfg)
        if not ss:
            print(_("no live sessions"))
            print("Are the hooks installed? -> ccdo install-hooks")
            return 1
        print("%-9s %-10s %-15s %-14s %-9s %-7s %s" %
              ("COLOR", "FROM", "LABEL", "TARGET", "STATE", "SOURCE", "DIR"))
        for s in ss:
            print("%-9s %-10s %-15s %-14s %-9s %-7s %s" %
                  (s["color"], (s.get("color_source") or "?")[:10], s["label"][:15],
                   s["target"][:14], s.get("state", "?"), s.get("source", "?"), s["cwd"]))
        print("\nSOURCE=hook means the match is exact; scan means it is a guess.")
        return 0

    if cmd == "auto":
        # ccdo auto <hedef> on|off
        if len(rest) < 2 or rest[1] not in ("on", "off"):
            sys.stderr.write("usage: ccdo auto <target> on|off\n")
            return 2
        reg = Registry()
        rec = reg.by_target(rest[0])
        if not rec:
            sys.stderr.write("no registered session: %s\n" % rest[0])
            return 1
        reg.upsert(rec["session_id"], auto_advance=(rest[1] == "on"), advance_count=0)
        AutoPrefs().set(rec.get("cwd"), rest[1] == "on")
        ipc_send("refresh")
        print("%s auto-advance: %s" % (rest[0], rest[1]))
        return 0

    if cmd == "diag":
        print("== the Claude Code settings chain ==")
        reg = Registry()
        recs = list(reg.all().values()) or [{"cwd": os.getcwd(), "session_id": "(none)"}]
        for rec in recs:
            cwd = rec.get("cwd") or os.getcwd()
            print("\n-- session %s" % (rec.get("session_id") or "?"))
            print("   cwd        : %s" % cwd)
            print("   transcript : %s" % (rec.get("transcript") or "(not recorded)"))
            d = os.path.realpath(cwd)
            while True:
                for name in ("settings.local.json", "settings.json"):
                    p = os.path.join(d, ".claude", name)
                    if os.path.exists(p):
                        data = _read_json(p) or {}
                        print("   setting    : %s  theme=%r" % (p, data.get("theme")))
                parent = os.path.dirname(d)
                if parent == d:
                    break
                d = parent
            up = os.path.join(HOME, ".claude", "settings.json")
            if os.path.exists(up):
                print("   setting    : %s  theme=%r"
                      % (up, (_read_json(up) or {}).get("theme")))
            print("   theme choice: %r" % claude_theme_preference(cwd))
            print("   theme color : %r" % claude_theme_color(cwd))
            print("   session name: %r" % (transcript_title(rec.get("transcript"))
                                          or rec.get("title")))

        tdir = os.path.join(HOME, ".claude", "themes")
        print("\n== %s ==" % tdir)
        try:
            names = sorted(os.listdir(tdir))
        except OSError as e:
            names = []
            print("   (could not read: %s)" % e)
        for n in names:
            data = _read_json(os.path.join(tdir, n)) or {}
            ov = data.get("overrides") or {}
            print("   %-24s claude=%r promptBorder=%r"
                  % (n, ov.get("claude"), ov.get("promptBorder")))
        if not names:
            print("   (no custom theme — built-in themes yield no color)")
        return 0

    if cmd == "paste-check":
        return paste_check()

    if cmd == "targets":
        panes = tmux_panes()
        if not panes:
            print("no tmux panes found")
            return 1
        live = {s["target"] for s in discover_sessions(cfg)}
        for target, c, cwd, title, pid, pane_id in panes:
            mark = " *" if (target in live or pane_id in live) else ""
            print("%-18s %-7s %-10s %-7s %-32s %s" % (
                target + mark, pane_id, c, pid, cwd, title))
        print("\n* = ccdo counts this as Claude Code.")
        return 0

    if cmd in ("version", "--version", "-V"):
        print("ccdo %s" % VERSION)
        cache = (check_update(cfg, force="--check" in rest)
                 if "--check" in rest else read_update_cache())
        latest = cache.get("latest", "")
        if newer_version(latest):
            print(_("new version available: %s") % latest)
            notes = plain_markdown(cache.get("notes"))
            if notes:
                print("\n%s\n" % notes)
            print(_("to update: ccdo update"))
        elif "--check" in rest:
            print(_("up to date") if latest else _("could not read version info"))
        return 0

    if cmd == "update":
        # --apply runs the installer for you. It is opt-in on purpose: piping a
        # remote script into a shell is not something to do behind the user's
        # back, so without the flag we only print the command.
        apply = "--apply" in rest
        assume_yes = "--yes" in rest or "-y" in rest
        cache = check_update(cfg, force=True)
        latest = cache.get("latest", "")
        if newer_version(latest):
            print("%s -> %s" % (VERSION, latest))
            notes = plain_markdown(cache.get("notes"))
            if notes:
                print("\n%s" % notes)
        elif latest:
            print(_("already up to date (%s)") % VERSION)

        if not apply:
            print("\n%s\n" % update_command())
            print(_("The installer replaces ccdo in place; your settings, queue"))
            print(_("and history stay put. Then: systemctl --user restart ccdo"))
            print(_("To run it now: ccdo update --apply"))
            return 0

        print("\n%s\n" % update_command())
        if not assume_yes:
            try:
                answer = input(_("Run it now? [y/N] ")).strip().lower()
            except EOFError:
                answer = ""
            if answer not in ("y", "yes"):
                print(_("cancelled"))
                return 1
        rc = subprocess.call(update_command(), shell=True)
        if rc != 0:
            sys.stderr.write(_("the installer failed (exit %d)\n") % rc)
            return rc
        if IS_MAC:
            run_cmd(["launchctl", "kickstart", "-k",
                     "gui/%d/com.corevider.ccdo" % os.getuid()])
        else:
            run_cmd(["systemctl", "--user", "restart", "ccdo"])
        print(_("updated — the tray was restarted"))
        return 0

    if cmd == "path":
        for label, path in (("config", CONFIG_PATH), ("queue", STORE_PATH),
                            ("md", QUEUE_MD), ("history", HISTORY_PATH),
                            ("log", EVENTS_PATH), ("auto", AUTO_PATH),
                            ("images", IMAGES_DIR), ("version", UPDATE_PATH)):
            print("%-7s: %s" % (label, path))
        return 0

    sys.stderr.write("unknown command: %s\n" % cmd)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
