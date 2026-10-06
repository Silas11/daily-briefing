"""Testet Kandidaten-Feed-URLs: Status, Eintragszahl, juengster Eintrag."""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser
import requests

UA = "Mozilla/5.0 (compatible; daily-briefing/0.1; +personal-use)"

CANDIDATES = {
    "tagesschau": ["https://www.tagesschau.de/index~rss2.xml"],
    "tagesschau_wirtschaft": ["https://www.tagesschau.de/wirtschaft/index~rss2.xml"],
    "deutschlandfunk": [
        "https://www.deutschlandfunk.de/nachrichten-100.rss",
        "https://www.deutschlandfunk.de/politikportal-100.rss",
    ],
    "spiegel": ["https://www.spiegel.de/schlagzeilen/index.rss"],
    "spiegel_wirtschaft": ["https://www.spiegel.de/wirtschaft/index.rss"],
    "zeit": ["https://newsfeed.zeit.de/index"],
    "zeit_wirtschaft": ["https://newsfeed.zeit.de/wirtschaft/index"],
    "handelsblatt": [
        "https://www.handelsblatt.com/contentexport/feed/top-themen",
        "https://www.handelsblatt.com/contentexport/feed/unternehmen",
        "https://www.handelsblatt.com/contentexport/feed/finanzen",
    ],
    "faz_wirtschaft": [
        "https://www.faz.net/rss/aktuell/wirtschaft/",
        "https://www.faz.net/rss/aktuell/wirtschaft/unternehmen/",
    ],
    "manager_magazin": [
        "https://www.manager-magazin.de/unternehmen/index.rss",
        "https://www.manager-magazin.de/index.rss",
    ],
    "wiwo": [
        "https://www.wiwo.de/contentexport/feed/rss/schlagzeilen",
        "https://www.wiwo.de/contentexport/feed/rss/unternehmen",
    ],
    "anthropic": [
        "https://www.anthropic.com/news/rss.xml",
        "https://www.anthropic.com/rss.xml",
        "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
        "https://raw.githubusercontent.com/taobojlen/anthropic-rss-feed/main/anthropic_news_rss.xml",
    ],
    "claude_code_releases": ["https://github.com/anthropics/claude-code/releases.atom"],
    "openai": ["https://openai.com/news/rss.xml", "https://openai.com/blog/rss.xml"],
    "deepmind": ["https://deepmind.google/blog/rss.xml", "https://deepmind.google/discover/blog/rss.xml"],
    "google_ai_blog": ["https://blog.google/technology/ai/rss/"],
    "the_decoder": ["https://the-decoder.de/feed/"],
    "heise": ["https://www.heise.de/rss/heise-atom.xml", "https://www.heise.de/rss/heise-top-atom.xml"],
    "hackernews": ["https://hnrss.org/frontpage", "https://news.ycombinator.com/rss"],
    "techcrunch": [
        "https://techcrunch.com/feed/",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
    ],
    "kommunikation": [
        "https://kress.de/rss",
        "https://kress.de/rss/news.xml",
        "https://www.horizont.net/rss/",
        "https://meedia.de/feed",
        "https://www.prreport.de/feed/",
        "https://www.socialmediatoday.com/feeds/news/",
        "https://www.linkedin.com/blog/rss",
    ],
}


def probe(url):
    t0 = time.time()
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20, allow_redirects=True)
        d = feedparser.parse(r.content)
        n = len(d.entries)
        newest = None
        for e in d.entries:
            t = e.get("published_parsed") or e.get("updated_parsed")
            if t:
                dt = datetime(*t[:6], tzinfo=timezone.utc)
                newest = dt if newest is None or dt > newest else newest
        age = None
        if newest:
            age = round((datetime.now(timezone.utc) - newest).total_seconds() / 3600, 1)
        return url, r.status_code, n, age, f"{time.time() - t0:.1f}s", ""
    except Exception as ex:  # noqa: BLE001
        return url, "ERR", 0, None, f"{time.time() - t0:.1f}s", str(ex)[:80]


def main():
    jobs = [(name, u) for name, urls in CANDIDATES.items() for u in urls]
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda j: (j[0], probe(j[1])), jobs))
    for name, (url, status, n, age, dur, err) in results:
        ok = "OK " if status == 200 and n > 0 else "BAD"
        print(f"{ok} {name:22} {status!s:4} items={n:3} newest_age_h={age!s:7} {dur:6} {url} {err}")


if __name__ == "__main__":
    sys.exit(main())
