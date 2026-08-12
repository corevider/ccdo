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
import sys
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
    appkit.NSImage = types.SimpleNamespace(
        alloc=lambda: Alloc(lambda *a: types.SimpleNamespace(
            setSize_=lambda s: None, setTemplate_=lambda f: state.__setitem__("template", f))))
    appkit.NSAlert = types.SimpleNamespace(alloc=lambda: Alloc(lambda *a: None))
    appkit.NSTextField = types.SimpleNamespace(alloc=lambda: Alloc(lambda *a: None))
    appkit.NSWorkspace = types.SimpleNamespace(sharedWorkspace=lambda: None)
    appkit.NSVariableStatusItemLength = -1
    appkit.NSApplicationActivationPolicyAccessory = 1

    for name, mod in (("objc", objc), ("Foundation", foundation), ("AppKit", appkit)):
        sys.modules[name] = mod
    return state


def run_app():
    state = install_stubs({})
    try:
        ok = jd.start_mac_gui()
    finally:
        for name in ("objc", "Foundation", "AppKit"):
            sys.modules.pop(name, None)
    return ok, state


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
jd.atomic_write(jd.CONFIG_PATH, json.dumps(
    {"process_match": [NEEDLE], "pane_match": [NEEDLE],
     "check_updates": False}) + "\n")

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

for t in store.all():
    store.delete(t["id"])
reg.drop("mac-test")

raise SystemExit(r.finish())
