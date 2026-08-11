#!/usr/bin/env python3
"""Translation layer: English source strings, JSON catalogs beside them.

A missing or broken catalog must never break the app — an untranslated string
falls back to its English source, which is always readable. And every string
the code asks for has to exist in a shipped catalog, or that language quietly
turns into a half-translated interface.
"""
import json
import os
import re

from harness import jd, Results

r = Results("translation")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES = os.path.join(ROOT, "locales")


def source_strings():
    """Every string the code passes through _(), plus the tables it looks up."""
    src = open(os.path.join(ROOT, "ccdo.py"), encoding="utf-8").read()

    def unescape(s):
        return s.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')

    keys = set()
    for m in re.finditer(r'_\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)\)', src):
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
        keys.add(unescape("".join(parts)))
    for section, fields in jd.SETTINGS_SCHEMA:
        keys.add(section)
        for f in fields:
            keys.add(f[2])
            if f[3]:
                keys.add(f[3])
    for row in jd.STATE_MARKS.values():
        keys.add(row[1])
    # Translated at runtime from the config value, so no literal _() to find.
    keys.add(jd.DEFAULT_CONFIG["file_ref_template"])
    return keys


# ------------------------------------------------------------- catalogs

keys = source_strings()
r.check(len(keys) > 50, "source strings found", "%d" % len(keys))

catalogs = sorted(n for n in os.listdir(LOCALES) if n.endswith(".json"))
r.check(catalogs, "at least one catalog ships", str(catalogs))

for name in catalogs:
    code = name[:-5]
    with open(os.path.join(LOCALES, name), encoding="utf-8") as f:
        cat = json.load(f)
    entries = {k: v for k, v in cat.items() if k != "__meta__"}

    missing = sorted(keys - set(entries))
    r.check(not missing, "%s: every source string is translated" % code,
            "%d missing: %s" % (len(missing), missing[:2]))

    stale = sorted(set(entries) - keys)
    r.check(not stale, "%s: no entries left over from removed strings" % code,
            "%d stale: %s" % (len(stale), stale[:2]))

    empty = [k for k, v in entries.items() if not isinstance(v, str) or not v.strip()]
    r.check(not empty, "%s: no empty translations" % code, str(empty[:2]))

    # A format placeholder dropped in translation crashes at runtime.
    def slots(text):
        return sorted(re.findall(r"%(?:\((\w+)\)|)([sd])", text))

    bad = [k for k, v in entries.items() if slots(k) != slots(v)]
    r.check(not bad, "%s: format placeholders survive translation" % code,
            str(bad[:2]))


# ------------------------------------------------------------- fallback

jd.load_language("en")
r.check(jd._("Save") == "Save", "English passes through untouched")

jd.load_language("tr")
r.check(jd._("Save") == "Kaydet", "Turkish catalog is applied")
r.check(jd._("a string that does not exist") == "a string that does not exist",
        "unknown string falls back to its source")

r.check(jd.load_language("zz") == "en", "unknown language falls back to English")
r.check(jd._("Save") == "Save", "fallback clears the previous catalog")

r.check(jd.load_language(None) in jd.available_languages(),
        "auto picks a language we actually have")
r.check("en" in jd.available_languages() and "tr" in jd.available_languages(),
        "en and tr are both offered", str(jd.available_languages()))


# --------------------------------------------------- language detection

def with_env(**env):
    old = {k: os.environ.get(k) for k in ("LC_ALL", "LC_MESSAGES", "LANG")}
    for k in old:
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in env.items() if v})
    try:
        return jd.desktop_language()
    finally:
        for k, v in old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


r.check(with_env(LANG="tr_TR.UTF-8") == "tr", "LANG gives the language code")
r.check(with_env(LANG="en_US.UTF-8", LC_ALL="tr_TR.UTF-8") == "tr",
        "LC_ALL wins over LANG")
r.check(with_env(LANG="C") == "en", "C locale means English")
r.check(with_env() == "en", "no locale set means English")


# --------------------------------------- language-specific question patterns

jd.load_language("tr")
pats = jd.language_question_patterns()
r.check(pats, "Turkish contributes question patterns", "%d" % len(pats))
asked, _why = jd.turn_ends_with_question("Bunu yapayım mı", None)
r.check(asked, "a Turkish question is recognised once tr is loaded")

jd.load_language("en")
r.check(not jd.language_question_patterns(),
        "English carries no extra patterns")
asked, _why = jd.turn_ends_with_question("Should I continue", None)
r.check(asked, "an English question is recognised without any catalog")

raise SystemExit(r.finish())
