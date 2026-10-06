"""Zieht den Volltext frei zugaenglicher Artikel fuer die relevanten Cluster. Ergaenzt out/plan.json um 'material'.

Paywall-Quellen werden nie abgerufen (nur Teaser). Pro Cluster hoechstens 2 Artikel.
"""
import json
from concurrent.futures import ThreadPoolExecutor

import requests
import trafilatura

from common import OUT, USER_AGENT, get_logger

log = get_logger("enrich")
MIN_RELEVANCE = 5
PER_CLUSTER = 2
CHARS = 3000


def get_text(item):
    try:
        r = requests.get(item["link"], headers={"User-Agent": USER_AGENT}, timeout=20)
        r.raise_for_status()
        text = trafilatura.extract(r.text, include_comments=False, include_tables=False) or ""
    except Exception as ex:  # noqa: BLE001
        log.warning("Volltext %s fehlgeschlagen: %s", item["source"], str(ex)[:80])
        return None
    if len(text) < 400:  # Teaser-Seite, Cookie-Wall oder Bezahlschranke
        return None
    return {"source": item["source"], "text": text[:CHARS].rsplit(" ", 1)[0]}


def main():
    items = {i["id"]: i for i in json.loads((OUT / "items.json").read_text(encoding="utf-8"))["items"]}
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    jobs = []
    for ci, c in enumerate(plan["cluster"]):
        if c["relevanz"] < MIN_RELEVANCE:
            continue
        cands = [items[i] for i in c["item_ids"] if i in items and not items[i]["paywall"]]
        cands.sort(key=lambda i: -i["weight"])
        jobs += [(ci, it) for it in cands[: PER_CLUSTER + 1]]
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda j: (j[0], get_text(j[1])), jobs))
    for c in plan["cluster"]:
        c["material"] = []
    for ci, res in results:
        if res and len(plan["cluster"][ci]["material"]) < PER_CLUSTER:
            plan["cluster"][ci]["material"].append(res)
    got = sum(1 for c in plan["cluster"] if c["material"])
    log.info("Volltext fuer %d von %d Clustern", got, len(plan["cluster"]))
    (OUT / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
