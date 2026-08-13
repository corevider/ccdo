#!/usr/bin/env python3
"""The macOS menu bar app, driven with PyObjC stubbed out.

It cannot be run on the machine that builds it, and the first version shipped
with `discover_sessions(cfg)[0]` — a call that reads fine but returns a list,
so the app died on launch with an IndexError. That class of mistake is exactly
what a stub can catch: the Cocoa calls are faked, but every line of our own
logic runs, against the real core.

What this does not check is whether Cocoa likes what we hand it. Only a Mac
can say that.
"""
import os
import sys
import time
import types

from harness import jd, Results, CFG

r = Results("macOS menu bar")


# ------------------------------------------------------------------ stubs

class Menu:
    def __init__(self):
        self.items = []

    def setAutoenablesItems_(self, flag):
        self.autoenables = flag

    def addItem_(self, item):
        self.items.append(item)

    def removeAllItems(self):
        self.items = []

    def titles(self):
        return [i.title for i in self.items]


class Item:
    def __init__(self, title="", action=None):
        self.title, self.action = title, action
        self.tag_value, self.target, self.enabled, self.submenu = 0, None, True, None

    def setTag_(self, tag):
        self.tag_value = tag

    def tag(self):
        return self.tag_value

    def setTarget_(self, t):
        self.target = t

    def setEnabled_(self, flag):
        self.enabled = flag

    def setSubmenu_(self, menu):
        self.submenu = menu


class Button:
    def __init__(self):
        self.tooltip = self.title = None
        self.image = None

    def setImage_(self, img):
        self.image = img

    def setTitle_(self, t):
        self.title = t

    def setToolTip_(self, t):
        self.tooltip = t


class StatusItem:
    def __init__(self):
        self._button, self.menu = Button(), None

    def button(self):
        return self._button

    def setMenu_(self, menu):
        self.menu = menu


class Alloc:
    """Stands in for the alloc().init...() dance, whatever the initialiser."""

    def __init__(self, make):
        self.make = make

    def __getattr__(self, name):
        def init(*a, **kw):
            return self.make(*a)
        return init


class Widget(object):
    """A view that shrugs at every setter but answers real calls itself.

    Only set*_ is waved through: a typo in anything we actually read — string,
    textContainer, indexOfSelectedItem — should still be an AttributeError.
    """

    @classmethod
    def alloc(cls):
        return cls()

    def initWithFrame_(self, frame):
        self.frame = frame
        return self

    def __getattr__(self, name):
        if name.startswith("set"):
            return lambda *a, **kw: None
        raise AttributeError(name)


class TextView(Widget):
    def initWithFrame_(self, frame):
        Widget.initWithFrame_(self, frame)
        self.text, self.caret, self.plain_pastes = "", 0, 0
        self.selected_all = False
        return self

    def selectAll_(self, sender):
        self.selected_all = True

    def copy_(self, sender):
        pass

    def cut_(self, sender):
        pass

    def undoManager(self):
        return None

    def registerForDraggedTypes_(self, kinds):
        self.dragged_types = list(kinds)

    def string(self):
        return self.text

    def selectedRange(self):
        return types.SimpleNamespace(location=self.caret)

    def insertText_replacementRange_(self, text, rng):
        self.text += text
        self.caret = len(self.text)

    def pasteAsPlainText_(self, sender):
        self.plain_pastes += 1

    def textContainer(self):
        return Widget()

    def type(self, text):
        self.text += text
        self.caret = len(self.text)


class ScrollView(Widget):
    def setDocumentView_(self, view):
        self.document = view


class PopUp(Widget):
    def initWithFrame_pullsDown_(self, frame, pulls_down):
        self.titles, self.index = [], 0
        return self

    def addItemWithTitle_(self, title):
        self.titles.append(title)

    def selectItemAtIndex_(self, i):
        self.index = i

    def indexOfSelectedItem(self):
        return self.index


class PushButton(Widget):
    def initWithFrame_(self, frame):
        Widget.initWithFrame_(self, frame)
        self.title, self.tag_value, self.key, self.mask = "", 0, "", 0
        return self

    def setTitle_(self, t):
        self.title = t

    def setTag_(self, tag):
        self.tag_value = tag

    def setKeyEquivalent_(self, key):
        self.key = key

    def setKeyEquivalentModifierMask_(self, mask):
        self.mask = mask

    def tag(self):
        return self.tag_value


class Window(Widget):
    def initWithContentRect_styleMask_backing_defer_(self, rect, style, backing, defer):
        self.rect, self.style = rect, style
        self.views, self.title, self.delegate = [], "", None
        self.visible, self.first_responder = False, None
        return self

    def contentView(self):
        return self

    def addSubview_(self, view):
        self.views.append(view)

    def center(self):
        pass

    def setTitle_(self, title):
        self.title = title

    def setDelegate_(self, delegate):
        self.delegate = delegate

    def makeKeyAndOrderFront_(self, sender):
        self.visible = True

    def makeFirstResponder_(self, view):
        self.first_responder = view

    def close(self):
        self.visible = False
        if self.delegate is not None:
            self.delegate.windowWillClose_(
                types.SimpleNamespace(object=lambda: self))


class Data(object):
    def __init__(self, blob):
        self.blob = blob

    def writeToFile_atomically_(self, path, atomically):
        with open(path, "wb") as fh:
            fh.write(self.blob)
        return True


class Image(object):
    """An NSImage as the pasteboard hands it over: TIFF inside."""

    def __init__(self, tiff):
        self.tiff = tiff

    def TIFFRepresentation(self):
        return Data(self.tiff)


class Pasteboard(object):
    """A clipboard holding whatever a test puts on it."""

    counter = [0]

    def __init__(self, png=None, tiff=None, files=(), images=()):
        self.png, self.tiff = png, tiff
        self.files, self.images = list(files), list(images)
        # Every new clipboard is a new change count, as macOS reports it.
        Pasteboard.counter[0] += 1
        self.count = Pasteboard.counter[0]

    def changeCount(self):
        return self.count

    def readObjectsForClasses_options_(self, classes, options):
        if any(c is Image for c in classes):
            return list(self.images)
        return [types.SimpleNamespace(path=lambda p=f: p) for f in self.files]

    def types(self):
        return [k for k, v in (("png", self.png), ("tiff", self.tiff)) if v]

    def dataForType_(self, kind):
        blob = {"png": self.png, "tiff": self.tiff}.get(kind)
        return Data(blob) if blob else None


def install_stubs(state):
    objc = types.ModuleType("objc")
    objc.selector = lambda fn, signature=None: fn

    foundation = types.ModuleType("Foundation")

    class NSObject:
        """Just enough of the alloc/init dance for a subclass to be built."""

        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

    foundation.NSObject = NSObject
    foundation.NSURL = type("NSURL", (), {"URLWithString_": staticmethod(lambda u: u)})
    foundation.NSMakeRect = lambda *a: a

    class NSTimer:
        @staticmethod
        def scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(*a):
            state["timer"] = a
    foundation.NSTimer = NSTimer

    appkit = types.ModuleType("AppKit")

    class NSApp:
        @staticmethod
        def sharedApplication():
            return state.setdefault("app", types.SimpleNamespace(
                setActivationPolicy_=lambda p: state.__setitem__("policy", p),
                activateIgnoringOtherApps_=lambda f: None,
                terminate_=lambda s: state.__setitem__("terminated", True),
                run=lambda: state.__setitem__("ran", True)))
    appkit.NSApplication = NSApp
    appkit.NSStatusBar = type("NSStatusBar", (), {
        "systemStatusBar": staticmethod(
            lambda: types.SimpleNamespace(
                statusItemWithLength_=lambda n: state.setdefault("status", StatusItem())))})
    appkit.NSMenu = types.SimpleNamespace(alloc=lambda: Alloc(lambda *a: Menu()))
    appkit.NSMenuItem = types.SimpleNamespace(
        alloc=lambda: Alloc(lambda *a: Item(*a[:2])),
        separatorItem=staticmethod(lambda: Item("---")))
    Image.alloc = staticmethod(lambda: Alloc(lambda *a: types.SimpleNamespace(
        setSize_=lambda s: None,
        setTemplate_=lambda f: state.__setitem__("template", f))))
    appkit.NSImage = Image
    appkit.NSAlert = types.SimpleNamespace(alloc=lambda: Alloc(lambda *a: None))
    appkit.NSWorkspace = types.SimpleNamespace(sharedWorkspace=lambda: None)
    appkit.NSVariableStatusItemLength = -1
    appkit.NSApplicationActivationPolicyAccessory = 1

    appkit.NSWindow = Window
    appkit.NSTextView = TextView
    appkit.NSScrollView = ScrollView
    appkit.NSPopUpButton = PopUp
    appkit.NSButton = PushButton
    appkit.NSFont = types.SimpleNamespace(systemFontOfSize_=lambda size: None)
    appkit.NSPasteboard = types.SimpleNamespace(
        generalPasteboard=lambda: state.get("pasteboard"))
    appkit.NSPasteboardTypePNG = "png"
    appkit.NSPasteboardTypeTIFF = "tiff"
    appkit.NSBitmapImageRep = types.SimpleNamespace(
        imageRepWithData_=lambda data: types.SimpleNamespace(
            representationUsingType_properties_=lambda kind, props:
            Data(b"png-of-" + data.blob) if kind == jd.PNG_FILE_TYPE else None))
    # The AppKit constants are read with getattr and a fallback, so leaving
    # them out here exercises that path.

    for name, mod in (("objc", objc), ("Foundation", foundation), ("AppKit", appkit)):
        sys.modules[name] = mod
    return state


def run_app():
    """Start the app and leave the stubs in place.

    The window code imports AppKit again when an image is pasted, so the fakes
    have to outlive the call. They are removed at the end of the file.
    """
    state = install_stubs({})
    jd._MAC_WINDOWS[:] = []
    return jd.start_mac_gui(), state


# ------------------------------------------------------------------ empty

# The harness isolates the queue, but not tmux: discover_sessions would find
# the panes actually running on the machine and put them in the menu. Match
# nothing, so only what this test registers shows up.
#
# The needle is joined at run time on purpose. Written as one literal it ends
# up in this file's own command line, the scan walks the pane's process tree,
# finds it there and reports the test itself as a live session.
import json                                                       # noqa: E402
NEEDLE = "ccdo" + "-matches-" + "nothing"
jd.ensure_dirs()
SHOTS = os.path.join(jd.DATA_DIR, "shots")
os.makedirs(SHOTS, exist_ok=True)
jd.atomic_write(jd.CONFIG_PATH, json.dumps(
    {"process_match": [NEEDLE], "pane_match": [NEEDLE],
     "check_updates": False, "screenshot_dir": SHOTS}) + "\n")

store = jd.Store(CFG)
for t in store.all():
    store.delete(t["id"])
jd.Registry().drop("mac-test")

ok, state = run_app()
r.check(ok is True, "it starts with nothing registered at all")
r.check(state.get("ran") is True, "the run loop is entered")
r.check(state.get("policy") == 1,
        "it registers as an accessory app — menu bar, no Dock icon")
r.check(state.get("template") is True,
        "the icon is a template, so macOS recolours it for the menu bar")

titles = state["status"].menu.titles()
r.check(any("Quick note" in t for t in titles), "the quick note item is there", str(titles))
r.check(any("Quit" in t for t in titles), "and a way out", str(titles))
r.check(any("no live sessions" in t for t in titles),
        "with no sessions it says so rather than showing an empty menu", str(titles))


# ---------------------------------------------------------------- sessions

reg = jd.Registry()
reg.upsert("mac-test", target="%9", cwd="/home/you/dev/api", state="idle",
           label="api-server", title="api-server")
store.add("Retry the upload once before giving up", target="%9", priority=1)
store.add("Split the parser out of the request handler", target="%9")

ok, state = run_app()
titles = state["status"].menu.titles()
r.check(any(t.startswith("api-server — 2") for t in titles),
        "a session shows with its pending count", str(titles))

session_item = next(i for i in state["status"].menu.items
                    if i.title.startswith("api-server"))
sub = session_item.submenu.titles()
r.check(any("Send next task" in t for t in sub), "the submenu can send the next one", str(sub))
r.check(any("Retry the upload" in t for t in sub), "and lists the tasks", str(sub))
r.check(any(t.startswith("★") for t in sub), "a starred task is marked", str(sub))

task_row = next(i for i in session_item.submenu.items if "Retry the upload" in i.title)
r.check(sorted(task_row.submenu.titles()) == ["Delete", "Done", "Send"],
        "each task carries its three actions", str(task_row.submenu.titles()))

r.check(state["status"].button().tooltip and "2" in state["status"].button().tooltip,
        "the tooltip carries the count, since the icon has no badge",
        state["status"].button().tooltip)


# ----------------------------------------------------------------- actions

# Every item that does something must resolve to a callable, or the menu looks
# alive and does nothing.
def walk(menu):
    for item in menu.items:
        yield item
        if item.submenu is not None:
            for sub_item in walk(item.submenu):
                yield sub_item


tagged = [i for i in walk(state["status"].menu) if i.tag()]
r.check(tagged, "items carry tags", str(len(tagged)))
r.check(all(i.tag() in jd._MAC_ACTIONS for i in tagged),
        "every tagged item resolves to a handler")
r.check(all(callable(jd._MAC_ACTIONS[i.tag()]) for i in tagged),
        "and every handler is callable")
r.check(len({i.tag() for i in tagged}) == len(tagged),
        "no two items share a tag — they would run each other's action")

done = next(i for i in walk(state["status"].menu) if i.title == "Done")
jd._MAC_ACTIONS[done.tag()]()
r.check(len(store.pending("%9")) == 1, "Done really takes the task out of the queue")


# ------------------------------------------------------------- note window

def open_quick_note():
    item = next(i for i in state["status"].menu.items if "Quick note" in i.title)
    jd._MAC_ACTIONS[item.tag()]()
    return jd._MAC_WINDOWS[-1]


win = open_quick_note()
r.check(len(jd._MAC_WINDOWS) == 1, "the quick note item opens a window")
r.check(win.picker.titles[0] == "Inbox" and "api-server" in win.picker.titles,
        "the picker offers the inbox and every live session",
        str(win.picker.titles))
r.check(win.picker.index == 0, "a quick note starts on the inbox")

buttons = [v for v in win.win.views if isinstance(v, PushButton)]
r.check(len(buttons) == 2, "add, and add and send", str([b.title for b in buttons]))
send = next(b for b in buttons if "send" in b.title)
r.check(send.key == "\r" and send.mask,
        "send is Command+Return — Return alone belongs to the text")

r.check(open_quick_note() is win and len(jd._MAC_WINDOWS) == 1,
        "asking again raises the open window instead of a second one")

# A rebuild used to clear every action, which left the buttons of an open
# window pointing at nothing.
tag = buttons[0].tag()
scan = next(i for i in state["status"].menu.items if i.title == "Scan sessions")
jd._MAC_ACTIONS[scan.tag()]()
r.check(tag in jd._MAC_ACTIONS, "the window's buttons survive a menu rebuild")

win.tv.type("Two lines\nof note")
win.submit(False)
queued = [t for t in store.all() if t["status"] == "pending"]
r.check(any(t["text"] == "Two lines\nof note" and t["target"] is None
            for t in queued), "the note is queued, newlines and all",
        str([t["text"] for t in queued]))
r.check(not jd._MAC_WINDOWS and tag not in jd._MAC_ACTIONS,
        "submitting closes the window and gives its tags back")

session_item = next(i for i in state["status"].menu.items
                    if i.title.startswith("api-server"))
note_item = next(i for i in session_item.submenu.items if "Note for" in i.title)
jd._MAC_ACTIONS[note_item.tag()]()
win = jd._MAC_WINDOWS[-1]
r.check(win.picker.titles[win.picker.index] == "api-server",
        "a session note opens with that session picked")
win.win.close()
r.check(not jd._MAC_WINDOWS, "closing the window unregisters it")


# ------------------------------------------------------------- image paste

win = open_quick_note()

# A screenshot is on the pasteboard as PNG already.
state["pasteboard"] = Pasteboard(png=b"shot")
win.tv.type("look at this")
win.tv.paste_(None)


def written(text, line=0):
    """The nth path out of the note, without the quotes it is written with."""
    lines = [l for l in text.splitlines() if l]
    r.check(lines[line].startswith('"') and lines[line].endswith('"'),
            "the path is quoted, so a name with spaces survives", lines[line])
    return lines[line][1:-1]


saved = written(win.tv.text, 1)
r.check(win.tv.text.startswith("look at this\n"),
        "a path pasted mid-line starts on a line of its own", repr(win.tv.text))
r.check(os.path.isfile(saved) and open(saved, "rb").read() == b"shot",
        "PNG bytes go to disk as they are, with no re-encoding", saved)
r.check(saved.startswith(jd.IMAGES_DIR), "and lands in the images folder", saved)

# Anything else — JPEG, HEIC, an image dragged out of Preview — is read
# through NSImage, which takes every flavour, and converted.
state["pasteboard"] = Pasteboard(images=[Image(b"one"), Image(b"two")])
win.tv.text, win.tv.caret = "", 0
win.tv.paste_(None)
lines_out = [l for l in win.tv.text.splitlines() if l]
r.check(len(lines_out) == 2, "two images take a line each", repr(win.tv.text))
r.check(open(written(win.tv.text, 0), "rb").read() == b"png-of-one",
        "and each is converted to PNG on the way in", lines_out[0])

state["pasteboard"] = Pasteboard(tiff=b"raw-tiff")
win.tv.text, win.tv.caret = "", 0
win.tv.paste_(None)
converted = written(win.tv.text)
r.check(os.path.isfile(converted)
        and open(converted, "rb").read() == b"png-of-raw-tiff",
        "and raw TIFF is converted on the way in", converted)

existing = os.path.join(jd.IMAGES_DIR, "already on disk.png")
open(existing, "wb").write(b"x")
state["pasteboard"] = Pasteboard(images=[Image(b"ignored")],
                                 files=[existing, "https://example.com/x.png"])
win.tv.text, win.tv.caret = "", 0
win.tv.paste_(None)
r.check(written(win.tv.text) == existing,
        "a copied file keeps its own path instead of being copied again",
        repr(win.tv.text))
r.check(len([l for l in win.tv.text.splitlines() if l]) == 1,
        "a link is not an attachment — it does not exist as a file",
        repr(win.tv.text))

state["pasteboard"] = Pasteboard()
win.tv.text, win.tv.caret = "", 0
win.tv.paste_(None)
r.check(win.tv.plain_pastes == 1 and not win.tv.text,
        "plain text still pastes as text")


# Command+V reaches paste: only because we answer it here: an accessory app
# has no menu bar, so there is no Edit menu to translate the key.
CMD, SHIFT, CTRL = 1 << 20, 1 << 17, 1 << 18


def key(ch, flags=CMD):
    return types.SimpleNamespace(modifierFlags=lambda: flags,
                                 charactersIgnoringModifiers=lambda: ch)


state["pasteboard"] = Pasteboard(png=b"by-command-v")
win.tv.text, win.tv.caret = "", 0
r.check(win.tv.performKeyEquivalent_(key("v")) is True,
        "Command+V is claimed by the note field")
r.check(open(written(win.tv.text), "rb").read() == b"by-command-v",
        "and it really pastes", repr(win.tv.text))
r.check(win.tv.performKeyEquivalent_(key("a")) is True and win.tv.selected_all,
        "Command+A selects all, since nothing else would")
r.check(win.tv.performKeyEquivalent_(key("\r")) is False,
        "Command+Return is left to the send button further down the chain")
r.check(win.tv.performKeyEquivalent_(key("v", 0)) is False,
        "a bare V is just a letter")
r.check(win.tv.performKeyEquivalent_(key("v", CMD | CTRL)) is False,
        "and Control+Command+V is not ours either")


# Command+Shift+4 writes a file and leaves the clipboard alone, so a paste
# straight after taking a screenshot has nothing to work with.
state["pasteboard"] = Pasteboard()
shot_path = os.path.join(SHOTS, "Screen Shot at 17.20.45.png")
open(shot_path, "wb").write(b"from-the-desktop")
win.tv.text, win.tv.caret, win.tv.plain_pastes = "", 0, 0
win.tv.paste_(None)
r.check(written(win.tv.text) == shot_path,
        "with an empty clipboard, a screenshot just taken is pasted instead",
        repr(win.tv.text))
r.check(win.tv.plain_pastes == 0, "and it does not also paste as text")

os.utime(shot_path, (1, 1))
win.tv.text, win.tv.caret, win.tv.plain_pastes = "", 0, 0
win.tv.paste_(None)
r.check(not win.tv.text and win.tv.plain_pastes == 1,
        "an old one is left alone — a paste must not surprise you")

# The clipboard is rarely empty: an image copied with Command+Control+Shift+4
# earlier in the day sits there for hours, and pasting it instead of the
# screenshot just taken is exactly the wrong answer.
state["pasteboard"] = Pasteboard(png=b"stale-clipboard")
jd.clipboard_touched_at(state["pasteboard"], now=time.time() - 600)
os.utime(shot_path, (time.time() + 2, time.time() + 2))
win.tv.text, win.tv.caret = "", 0
win.tv.paste_(None)
r.check(written(win.tv.text) == shot_path,
        "a screenshot taken since beats what has been on the clipboard for ten"
        " minutes", repr(win.tv.text))

# And the other way round: copy something now and that is what you meant.
os.utime(shot_path, (time.time() - 30, time.time() - 30))
state["pasteboard"] = Pasteboard(png=b"copied-just-now")
win.tv.text, win.tv.caret = "", 0
win.tv.paste_(None)
r.check(open(written(win.tv.text), "rb").read() == b"copied-just-now",
        "while a fresh copy beats a screenshot from half a minute ago",
        repr(win.tv.text))

r.check(jd.image_insert_text(["/a.png"], True) == '"/a.png"\n',
        "at the start of a line the path needs no leading newline")
r.check(jd.image_insert_text(["/a.png", "/b.png"], False)
        == '\n"/a.png"\n"/b.png"\n',
        "mid-line it gets one, and several images take a line each")


# ------------------------------------------------------------- drag and drop

r.check(any("file-url" in str(t) for t in win.tv.dragged_types),
        "the note field asks for dropped files", str(win.tv.dragged_types))

dropped = os.path.join(jd.IMAGES_DIR, "a report.pdf")
open(dropped, "wb").write(b"%PDF-1.4")


def drag(pb):
    return types.SimpleNamespace(draggingPasteboard=lambda: pb)


win.tv.text, win.tv.caret = "", 0
r.check(win.tv.draggingEntered_(drag(Pasteboard())) == 1,
        "a drag is welcome, and says so — otherwise the cursor refuses it")
r.check(win.tv.performDragOperation_(drag(Pasteboard(files=[dropped]))) is True,
        "the drop is taken")
r.check(written(win.tv.text) == dropped,
        "a PDF is as good as an image: Claude Code opens the path either way",
        repr(win.tv.text))

# Dragged out of a browser there is no file at all, only pixels.
win.tv.text, win.tv.caret = "", 0
win.tv.performDragOperation_(drag(Pasteboard(png=b"from-a-browser")))
r.check(open(written(win.tv.text), "rb").read() == b"from-a-browser",
        "pixels dragged in are saved, which a plain text view would drop",
        repr(win.tv.text))

r.check(win.tv.performDragOperation_(drag(Pasteboard())) is False,
        "and nothing droppable is refused, so the view can do what it likes")

win.win.close()
for t in store.all():
    store.delete(t["id"])
reg.drop("mac-test")
for name in ("objc", "Foundation", "AppKit"):
    sys.modules.pop(name, None)

raise SystemExit(r.finish())
