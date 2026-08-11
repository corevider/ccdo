#!/usr/bin/env python3
"""turn_ends_with_question must spot a turn that asks, and only those.

A false positive is cheap (one turn is skipped); a false negative is
expensive (a task is injected in place of the user's answer). The "not a
question" samples below are real shapes of text that upset that balance.
"""
import sys
from harness import jd, Results

# The Turkish patterns live in the locale file: loading tr enables them.
jd.load_language("tr")

ASKS = [
    ("a plain question", "Shader hazir. Noise katmanini da ekleyeyim mi?"),
    ("a choice question", "Iki secenek var. Hangisini tercih edersin?"),
    ("Turkish mi/mu with no question mark", "Testler gecti. Deploy edeyim mi"),
    ("English should I", "Done. Should I move on to the next phase?"),
    ("English would you like", "Refactor complete. Would you like me to also update the docs?"),
    ("an option list", "Bitti.\n\n1. Hizli ama kirli\n2. Yavas ama temiz\n\nHangisi?"),
    ("Turkish devam edeyim mi", "Kurulum tamam. Devam edeyim mi?"),
    ("let me know", "Patch applied. Let me know if you want the tests too."),
]

NOT_ASKS = [
    ("a question mark inside a code block",
     'Kod blogu icinde soru isareti var:\n```json\n{"ok": true, "q": "?"}\n```\nIslem tamamlandi.'),
    ("a question mid-sentence",
     '"Bu fonksiyon ne yapiyor?" diye sordugun kismi acikladim ve testleri gecirdim.'),
    ("a numbered summary list",
     "Ozet:\n1. Shader ayrildi\n2. Noise eklendi\n3. Testler gecti"),
    ("a plain ending", "Uc dosya degisti, hepsi derlendi. Islem bitti."),
    ("a question in a code comment", "```python\nif x:  # neden?\n    pass\n```"),
]

r = Results("question detection")
for label, text in ASKS:
    got, why = jd.turn_ends_with_question(text, {})
    r.check(got is True, "asks: %s" % label, why)
for label, text in NOT_ASKS:
    got, why = jd.turn_ends_with_question(text, {})
    r.check(got is False, "does not ask: %s" % label, why)

# An extra pattern from the config must work too
got, _ = jd.turn_ends_with_question(
    "Bu isi bitirdim, sirada ne var acaba",
    {"question_patterns": [r"sirada ne var"]})
r.check(got is True, "an extra pattern from the config")

sys.exit(r.finish())
