"""Sammelt Feed-Eintraege der letzten Stunden, dedupliziert und schreibt out/items.json."""
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit

import feedparser
import requests

from common import USER_AGENT, ensure_out, get_logger, load_yaml, retry

log = get_logger("fetch")

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
TITLE_SIM = 0.88


def clean_text(raw, limit):
    text = html.unescape(TAG_RE.sub(" ", raw or ""))
    text = WS_RE.sub(" ", text).strip()
    if text.lower() in {"none", "null"}:
        return ""
    return text[:limit].rsplit(" ", 1)[0] + " ..." if len(text) > limit else text


def norm_url(url):
    parts = urlsplit(url or "")
    return urlunsplit((parts.scheme, parts.netloc.lower().removeprefix("www."), parts.path.rstrip("/"), "", ""))


def norm_title(title):
    return re.sub(r"[^a-z0-9äöüß ]", "", (title or "").lower()).strip()


@retry(attempts=3, base_delay=2, exceptions=(requests.RequestException,))
def download(url):
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
    r.raise_for_status()
    return r.content


def entry_time(e):
    t = e.get("published_parsed") or e.get("updated_parsed")
    return datetime(*t[:6], tzinfo=timezone.utc) if t else None


def fetch_source(src, defaults, now):
    window = timedelta(hours=src.get("window_hours", defaults["window_hours"]))
    limit = src.get("max_items_per_source", defaults["max_items_per_source"])
    chars = defaults["teaser_chars"]
    try:
        feed = feedparser.parse(download(src["url"]))
    except Exception as ex:  # noqa: BLE001
        log.error("Quelle %s ausgefallen: %s", src["id"], ex)
        return src["id"], None
    items = []
    for e in feed.entries:
        ts = entry_time(e)
        if ts is None or now - ts > window:
            continue
        body = e.get("summary") or ""
        if e.get("content"):
            body = e["content"][0].get("value") or body
        items.append(
            {
                "title": clean_text(e.get("title"), 300),
                "source": src["name"],
                "source_id": src["id"],
                "ressort_hint": src["ressort"],
                "weight": src.get("weight", 1.0),
                "paywall": bool(src.get("paywall", False)),
                "teaser": clean_text(body, chars),
                "link": e.get("link", ""),
                "published": ts.isoformat(),
            }
        )
    items.sort(key=lambda i: i["published"], reverse=True)
    return src["id"], items[:limit]


def dedupe(items):
    """Fasst identische URLs und fast gleiche Titel zusammen. Die Zweitquelle bleibt als also_in erhalten."""
    kept, by_url = [], {}
    for it in sorted(items, key=lambda i: -i["weight"]):
        key = norm_url(it["link"])
        if key and key in by_url:
            by_url[key].setdefault("also_in", []).append(it["source"])
            continue
        nt = norm_title(it["title"])
        match = next((k for k in kept if SequenceMatcher(None, norm_title(k["title"]), nt).ratio() >= TITLE_SIM), None)
        if match:
            if it["source"] != match["source"]:
                match.setdefault("also_in", []).append(it["source"])
            continue
        kept.append(it)
        if key:
            by_url[key] = it
    for it in kept:
        it["also_in"] = sorted(set(it.get("also_in", [])))
    return kept


def main():
    cfg = load_yaml("sources.yaml")
    now = datetime.now(timezone.utc)
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda s: fetch_source(s, cfg["defaults"], now), cfg["sources"]))
    failed = [sid for sid, items in results if items is None]
    raw = [it for _, items in results if items for it in items]
    items = dedupe(raw)
    items.sort(key=lambda i: i["published"], reverse=True)
    for n, it in enumerate(items, 1):
        it["id"] = n
    out = ensure_out() / "items.json"
    out.write_text(
        json.dumps({"generated": now.isoformat(), "failed_sources": failed, "items": items}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    by_ressort = {}
    for it in items:
        by_ressort[it["ressort_hint"]] = by_ressort.get(it["ressort_hint"], 0) + 1
    log.info("%d Roh-Eintraege, %d nach Dedup, je Ressort %s, ausgefallen: %s", len(raw), len(items), by_ressort, failed or "keine")
    if len(failed) > len(cfg["sources"]) // 2:
        raise SystemExit("Mehr als die Haelfte der Quellen ausgefallen, Abbruch.")


if __name__ == "__main__":
    main()
