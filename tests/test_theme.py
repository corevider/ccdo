#!/usr/bin/env python3
"""The palette must follow the desktop's light/dark preference.

Colors feed from a single table; if the two palettes do not carry the same
keys, the CSS template raises KeyError on one side and the window comes up
unstyled. Detecting the preference must not trust a single source either: on
Yaru, color-scheme can say 'prefer-dark' while
gtk-application-prefer-dark-theme stays False.
"""
import re

from harness import jd, Results

r = Results("light/dark theme")

dark, light = jd.THEME_DARK, jd.THEME_LIGHT

r.check(set(dark) == set(light), "both palettes carry the same keys",
        str(set(dark) ^ set(light)))

ortak = [k for k in dark if dark[k] == light[k]]
r.check(set(ortak) <= {"mono", "r_lg", "r_md"},
        "every color key differs between the palettes", str(ortak))


def luminance(css_color):
    m = re.match(r"#([0-9a-fA-F]{6})$", css_color)
    if not m:
        return None
    v = int(m.group(1), 16)
    r_, g, b = (v >> 16) & 255, (v >> 8) & 255, v & 255
    return 0.299 * r_ + 0.587 * g + 0.114 * b


r.check(luminance(dark["bg"]) < 60, "the dark palette has a dark ground", dark["bg"])
r.check(luminance(light["bg"]) > 200, "the light palette has a light ground", light["bg"])
r.check(luminance(dark["text"]) > 200, "the dark palette has light text", dark["text"])
r.check(luminance(light["text"]) < 60, "the light palette has dark text", light["text"])

# Text against ground has to stay readable in both palettes.
for name, th in (("dark", dark), ("light", light)):
    gap = abs(luminance(th["text"]) - luminance(th["bg"]))
    r.check(gap > 150, "%s palette: text/ground contrast is sufficient" % name,
            "%.0f" % gap)
    gap = abs(luminance(th["dim"]) - luminance(th["bg"]))
    r.check(gap > 60, "%s palette: secondary text stays readable" % name, "%.0f" % gap)


# ------------------------------------------------------------- detection

class FakeSettings:
    def __init__(self, prefer_dark=False, name="Adwaita"):
        self.vals = {"gtk-application-prefer-dark-theme": prefer_dark,
                     "gtk-theme-name": name}

    def get_property(self, k):
        return self.vals[k]


def with_scheme(value, settings=None):
    """Exercise prefers_dark by faking the gsettings output."""
    real = jd.run_cmd
    jd.run_cmd = lambda args, timeout=10: (
        (0, value, "") if args[:2] == ["gsettings", "get"] else real(args, timeout))
    try:
        return jd.prefers_dark(settings)
    finally:
        jd.run_cmd = real


r.check(with_scheme("'prefer-dark'\n", FakeSettings(prefer_dark=False)) is True,
        "color-scheme prefer-dark wins even with the GTK flag False")
r.check(with_scheme("'prefer-light'\n", FakeSettings(prefer_dark=True)) is False,
        "color-scheme prefer-light wins even with the GTK flag True")
r.check(with_scheme("'default'\n", FakeSettings(prefer_dark=True)) is True,
        "with no preference we fall to the GTK flag")
r.check(with_scheme("'default'\n", FakeSettings(name="Yaru-olive-dark")) is True,
        "with no flag either, the theme name tells us")
r.check(with_scheme("'default'\n", FakeSettings(name="Yaru-olive")) is False,
        "a light theme name gives the light palette")

r.check(jd.active_theme(FakeSettings(name="Yaru")) is not None,
        "active_theme always returns a palette")

# ------------------------------------------------------- the send button

# The button takes its ground from the session color; fixed dark text
# disappeared on the darker tones.
r.check(jd.ink_for("#cd3131") == "#ffffff", "white text on a dark red ground")
r.check(jd.ink_for("#0dbc79") == "#ffffff", "white text on a mid green ground")
r.check(all(jd.ink_for(c) == "#ffffff" for c in jd.PALETTE),
        "every palette color gets white text")
r.check(jd.ink_for("#f5f0d0") == "#141518", "a very light ground falls back to dark text")
r.check(jd.ink_for(None) == "#ffffff", "no color means white")
r.check(jd.ink_for("bozuk") == "#ffffff", "a malformed value causes no trouble")

raise SystemExit(r.finish())
