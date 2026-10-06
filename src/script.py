"""Gemini Lauf 2: Sprechskript mit Wortbudget je Thema. Output out/script.txt."""
import argparse
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import llm
from common import CONFIG, OUT, PROMPTS, TIMEZONE, get_logger

log = get_logger("script")
RESSORT_ORDER = ["nachrichten", "wirtschaft", "tech", "kommunikation"]
WPM = 180  # Katja bei 1,2-facher Geschwindigkeit
WORDS_PER_RELEVANCE = 60
MIN_WORDS, MAX_WORDS = 45, 540  # 2 Saetze bis ca. 3 Minuten
TARGET_MIN, TARGET_MAX = 2700, 3600  # 15 bis 20 Minuten, Orientierung statt harter Grenze
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def allocate(clusters):
    """Wortbudget proportional zum Relevanzwert, gedeckelt durch die Materiallage.

    Ruhiger Tag bleibt kurz. Ist die Summe ueber dem Maximum, werden erst alle Budgets
    skaliert, dann die schwaechsten Themen gestrichen, bis das Gesamtziel passt.
    """
    topics = sorted(clusters, key=lambda c: -c["relevanz"])
    for c in topics:
        c["words"] = max(MIN_WORDS, min(MAX_WORDS, c["relevanz"] * WORDS_PER_RELEVANCE))
    total = sum(c["words"] for c in topics)
    while total > TARGET_MAX and topics:
        scale = TARGET_MAX / total
        for c in topics:
            c["words"] = max(MIN_WORDS, round(c["words"] * scale))
        total = sum(c["words"] for c in topics)
        if total > TARGET_MAX:
            topics.pop()
            total = sum(c["words"] for c in topics)
    if total < TARGET_MIN and sum(c["relevanz"] for c in topics) >= 60:
        scale = min(1.3, TARGET_MIN / total)
        for c in topics:
            c["words"] = min(MAX_WORDS, round(c["words"] * scale))
        total = sum(c["words"] for c in topics)
    keep = {id(c) for c in topics}
    ordered = [c for r in RESSORT_ORDER for c in sorted((x for x in clusters if x["ressort"] == r and id(x) in keep), key=lambda c: -c["relevanz"])]
    return ordered, total


def topics_block(topics):
    out = []
    for n, c in enumerate(topics, 1):
        hint = " (nur Paywall-Teaser, keine Details ergaenzen)" if c["nur_paywall"] else ""
        out.append(
            f"{n}. [{c['ressort']}] {c['thema']} | Wortbudget ca. {c['words']} | Quellen: {', '.join(c['quellen'])}{hint}\n"
            + "\n".join(f"   - {f}" for f in c["kernfakten"])
            + (f"\n   Einordnung (Vorschlag): {c['einordnung']}" if c["einordnung"] else "")
            + "".join(f"\n   Volltext {m['source']}: {m['text'][: c['words'] * 9]}" for m in c.get("material", []))
        )
    return "\n".join(out)


def clean(text):
    text = re.sub(r"[*_#`>]+", "", text)
    text = re.sub(r"\s*[–—]\s*", ", ", text)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"https?://\S+", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Budget und Prompt ausgeben, kein API-Aufruf")
    args = ap.parse_args()
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    topics, total = allocate(plan["cluster"])
    now = datetime.now(ZoneInfo(TIMEZONE))
    prompt = (PROMPTS / "script_prompt.md").read_text(encoding="utf-8").format(
        editorial=(CONFIG / "editorial.md").read_text(encoding="utf-8"),
        weekday=WEEKDAYS[now.weekday()],
        date_spoken=f"{now.day}. {MONTHS[now.month - 1]} {now.year}",
        target_words=total,
        topics=topics_block(topics),
    )
    log.info("%d Themen, Zielwortzahl %d (ca. %.1f Minuten)", len(topics), total, total / WPM)
    if args.dry_run:
        print(prompt)
        return
    text = clean(llm.generate(prompt, temperature=0.5))
    words = len(text.split())
    (OUT / "script.txt").write_text(text, encoding="utf-8")
    log.info("Skript: %d Woerter, ca. %.1f Minuten (Ziel %d)", words, words / WPM, total)


if __name__ == "__main__":
    main()
