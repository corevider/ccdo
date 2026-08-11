#!/usr/bin/env python3
"""The settings window is generated from SETTINGS_SCHEMA.

If the schema and DEFAULT_CONFIG drift apart, the window either writes a key
that does not exist or hides a setting that does — and both happen silently.
This keeps the two tied together.
"""
import json
import os

from harness import jd, Results

r = Results("settings")

KINDS = {"bool": bool, "int": int, "float": (int, float), "str": str,
         "choice": str, "lang": str}

fields = [f for _, group in jd.SETTINGS_SCHEMA for f in group]
keys = [f[0] for f in fields]

r.check(len(keys) == len(set(keys)), "no duplicate keys")

bad = [k for k in keys if k not in jd.DEFAULT_CONFIG]
r.check(not bad, "every key in the schema exists in DEFAULT_CONFIG", str(bad))

bad = [f[0] for f in fields if f[1] not in KINDS]
r.check(not bad, "every field kind is recognised", str(bad))

bad = [f[0] for f in fields
       if not isinstance(jd.DEFAULT_CONFIG[f[0]], KINDS[f[1]])]
r.check(not bad, "the field kind matches the default value's type", str(bad))

bad = [f[0] for f in fields if f[1] in ("int", "float") and len(f) < 6]
r.check(not bad, "numeric fields carry a lower and upper bound", str(bad))

bad = [f[0] for f in fields
       if f[1] in ("int", "float") and not f[4] <= jd.DEFAULT_CONFIG[f[0]] <= f[5]]
r.check(not bad, "the default sits inside the bounds", str(bad))

bad = [f[0] for f in fields
       if f[1] == "choice" and jd.DEFAULT_CONFIG[f[0]] not in f[4]]
r.check(not bad, "the choice list contains the default", str(bad))

# The language list is built from the catalogs at runtime, not fixed here.
lang = [f for f in fields if f[1] == "lang"]
r.check(len(lang) == 1 and lang[0][0] == "language",
        "the language field appears once in the schema", str([f[0] for f in lang]))
r.check(jd.DEFAULT_CONFIG["language"] == "auto", "the language default is auto")

# List-valued settings are not in the window; they are edited in the file.
lists = [k for k, v in jd.DEFAULT_CONFIG.items() if isinstance(v, (list, dict))]
r.check(not (set(lists) & set(keys)),
        "list-valued settings were kept out of the window", str(lists))

r.check("max_auto_advance" in keys, "the requested setting is in the window: max_auto_advance")


# ------------------------------------------------------------------ saving

jd.ensure_dirs()
jd.atomic_write(jd.CONFIG_PATH, json.dumps(
    {"max_auto_advance": 3, "written_by_hand": "keep me",
     "question_patterns": ["\\bonaylıyor musun\\b"]}, ensure_ascii=False))

cfg = jd.load_config()
merged = dict(cfg)
merged.update({"max_auto_advance": 9})
jd.save_config(merged)

with open(jd.CONFIG_PATH, encoding="utf-8") as f:
    on_disk = json.load(f)

r.check(on_disk["max_auto_advance"] == 9, "a changed setting is written to the file")
r.check(on_disk.get("written_by_hand") == "keep me",
        "an unknown key added by hand is preserved")
r.check(on_disk.get("question_patterns") == ["\\bonaylıyor musun\\b"],
        "a list setting absent from the window is not overwritten")
r.check(jd.load_config()["max_auto_advance"] == 9,
        "reading it back gives the new value")

raise SystemExit(r.finish())
