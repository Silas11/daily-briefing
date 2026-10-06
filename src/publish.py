"""Veroeffentlicht die Folge: GitHub-Release mit MP3, Feed neu schreiben, alte Folgen loeschen.

Env: GITHUB_REPOSITORY (owner/repo), GH_TOKEN (fuer gh CLI), FEED_SLUG (nicht erratbarer Feedname).
"""
import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from common import DOCS, OUT, ROOT, TIMEZONE, get_logger

log = get_logger("publish")
STATE = ROOT / "state" / "episodes.json"
RETENTION_DAYS = 14
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def gh(*args, check=True):
    return subprocess.run(["gh", *args], check=check, capture_output=True, text=True)


def load_episodes():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else []


def show_notes(plan):
    lines = []
    for c in sorted(plan.get("cluster", []), key=lambda c: -c["relevanz"])[:10]:
        lines.append(f"{c['thema']} ({', '.join(c['quellen'])})")
    head = "Themen heute: " + "; ".join(lines) + ". " if lines else ""
    return head + "KI-generierte Zusammenfassung von Pressematerial."


def build_feed(episodes, base_url, repo):
    items = []
    for e in sorted(episodes, key=lambda e: e["pubdate"], reverse=True):
        items.append(f"""    <item>
      <title>{escape(e['title'])}</title>
      <description>{escape(e['description'])}</description>
      <pubDate>{format_datetime(datetime.fromisoformat(e['pubdate']))}</pubDate>
      <guid isPermaLink="false">{escape(e['tag'])}</guid>
      <enclosure url="{escape(e['url'])}" length="{e['bytes']}" type="audio/mpeg"/>
      <itunes:duration>{e['duration']}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
    </item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Daily Briefing</title>
    <link>{escape(base_url)}</link>
    <language>de-DE</language>
    <description>Persönlicher Morgen-Podcast: Nachrichtenlage, Wirtschaft und Märkte, AI und Tech. KI-generiert aus öffentlichen Nachrichtenquellen.</description>
    <itunes:author>Daily Briefing</itunes:author>
    <itunes:image href="{escape(base_url)}cover.jpg"/>
    <itunes:explicit>false</itunes:explicit>
    <itunes:type>episodic</itunes:type>
{chr(10).join(items)}
  </channel>
</rss>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Kein Release, Feed mit Platzhalter-URL schreiben")
    ap.add_argument("--mp3", default=str(OUT / "episode.mp3"))
    args = ap.parse_args()

    repo = os.environ.get("GITHUB_REPOSITORY", "OWNER/daily-briefing")
    slug = os.environ.get("FEED_SLUG", "dev")
    owner, name = repo.split("/")
    base_url = f"https://{owner}.github.io/{name}/"
    now = datetime.now(ZoneInfo(TIMEZONE))
    tag = f"ep-{now:%Y-%m-%d}"
    mp3 = Path(args.mp3)
    asset = f"daily-briefing-{now:%Y-%m-%d}.mp3"
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8")) if (OUT / "plan.json").exists() else {}
    meta = json.loads((OUT / "episode.json").read_text(encoding="utf-8"))
    title = f"Daily Briefing, {WEEKDAYS[now.weekday()]}, {now.day}. {MONTHS[now.month - 1]} {now.year}"
    ep = {
        "tag": tag,
        "title": title,
        "description": show_notes(plan),
        "pubdate": now.astimezone(timezone.utc).isoformat(),
        "url": f"https://github.com/{repo}/releases/download/{tag}/{asset}",
        "bytes": mp3.stat().st_size,
        "duration": meta["duration_seconds"],
    }

    if not args.dry_run:
        upload = mp3.with_name(asset)
        upload.write_bytes(mp3.read_bytes())
        gh("release", "delete", tag, "--cleanup-tag", "-y", "--repo", repo, check=False)  # idempotent bei Wiederholung
        gh("release", "create", tag, str(upload), "--repo", repo, "--title", title, "--notes", ep["description"])
        log.info("Release %s erstellt", tag)

    episodes = [e for e in load_episodes() if e["tag"] != tag] + [ep]
    cutoff = now.astimezone(timezone.utc) - timedelta(days=RETENTION_DAYS)
    expired = [e for e in episodes if datetime.fromisoformat(e["pubdate"]) < cutoff]
    for e in expired:
        if not args.dry_run:
            gh("release", "delete", e["tag"], "--cleanup-tag", "-y", "--repo", repo, check=False)
        log.info("Abgelaufen und entfernt: %s", e["tag"])
    episodes = [e for e in episodes if e not in expired]

    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(episodes, ensure_ascii=False, indent=1), encoding="utf-8")
    DOCS.mkdir(exist_ok=True)
    feed_path = DOCS / f"feed-{slug}.xml"
    feed_path.write_text(build_feed(episodes, base_url, repo), encoding="utf-8")
    log.info("Feed %s mit %d Folgen. URL: %s%s", feed_path.name, len(episodes), base_url, feed_path.name)


if __name__ == "__main__":
    main()
