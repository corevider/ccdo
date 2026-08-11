#!/usr/bin/env python3
"""final_turn_text: the Stop hook can run before the turn's last message
has been written to the transcript.

A real case, measured: the message was written at 16:36:22.329 and the hook
updated the queue at 16:36:22.438 — 109 ms apart. Reading in that window makes
last_assistant_text return the previous turn's text, so a turn that ended in a
question looks question-free and a task is injected in place of the user's
answer. This test reproduces that race exactly.
"""
import sys
import threading
import time

from harness import jd, Results, transcript_lines, write_transcript, tmp_path

SORU = "Testi bitirdim. auto_advance'i acik mi birakayim?"
LINES = transcript_lines(SORU)
BASE, FINAL = LINES[:-1], LINES[-1]        # son satir = turu kapatan metin


def run(delay_ms, timeout=3.0):
    """Son metin delay_ms sonra yazilirsa hook ne karar verir?

    delay_ms=None: metin hic gelmez (tur yalniz arac cagrisiyla bitmis).
    """
    p = write_transcript(tmp_path("race-%s.jsonl" % delay_ms), BASE)
    if delay_ms is not None:
        def later():
            time.sleep(delay_ms / 1000.0)
            with open(p, "ab") as f:
                f.write(FINAL)
        threading.Thread(target=later, daemon=True).start()
    t0 = time.time()
    text = jd.final_turn_text(p, timeout=timeout)
    asked, _ = jd.turn_ends_with_question(text, {})
    return asked, time.time() - t0


r = Results("race (Stop hook vs transcript write)")

for delay in (0, 110, 800):
    asked, took = run(delay)
    r.check(asked is True, "the text lands %d ms later" % delay,
            "beklendi %.2fs" % took)

# Metin hic gelmezse ortada soru da yok: sonsuza kadar beklemek oto modunu
# tamamen kilitlerdi, o yuzden zaman asiminda gonderime izin veriyoruz.
asked, took = run(None, timeout=0.6)
r.check(asked is False, "a turn with no text (tool call only)",
        "zaman asimi %.2fs" % took)

# Beklemeyi kaldirinca hatanin geri geldigini gosteren regresyon kancasi
p = write_transcript(tmp_path("race-old.jsonl"), BASE)
old, _ = jd.turn_ends_with_question(jd.last_assistant_text(p), {})
r.check(old is False, "reading without waiting reproduces the old bug",
        "it sees the previous turn's text")

# transcript_has_turn_text'in kendisi
r.check(jd.transcript_has_turn_text(
    write_transcript(tmp_path("has-yes.jsonl"), LINES)) is True,
    "transcript_has_turn_text: text present")
r.check(jd.transcript_has_turn_text(
    write_transcript(tmp_path("has-no.jsonl"), BASE)) is False,
    "transcript_has_turn_text: no text")

sys.exit(r.finish())
