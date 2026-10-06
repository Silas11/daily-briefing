"""Gemini Lauf 1: Meldungen clustern und bewerten. Output out/plan.json und out/briefing.md."""
import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

import llm
from common import OUT, PROMPTS, CONFIG, TIMEZONE, get_logger

log = get_logger("edit")
RESSORT_ORDER = ["nachrichten", "wirtschaft", "tech", "kommunikation"]


class Cluster(BaseModel):
    thema: str = Field(description="Kurzer Arbeitstitel des Themas")
    ressort: str = Field(description="nachrichten, wirtschaft, tech oder kommunikation")
    relevanz: int = Field(ge=1, le=10)
    quellen_anzahl: int = Field(ge=1)
    quellen: list[str] = Field(description="Namen der berichtenden Quellen")
    nur_paywall: bool = Field(description="True, wenn alle Quellen Paywall-Teaser sind")
    kernfakten: list[str] = Field(description="Fakten ausschliesslich aus Titeln und Teasern")
    einordnung: str = Field(description="Hoechstens zwei Saetze, sonst leer")
    item_ids: list[int]


class Plan(BaseModel):
    cluster: list[Cluster]


def slim(items):
    keys = ("id", "title", "source", "ressort_hint", "weight", "paywall", "teaser", "also_in")
    return [{k: i[k] for k in keys} for i in items]


def build_prompt(items, now):
    tpl = (PROMPTS / "edit_prompt.md").read_text(encoding="utf-8")
    editorial = (CONFIG / "editorial.md").read_text(encoding="utf-8")
    return tpl.format(editorial=editorial, date=now.strftime("%Y-%m-%d"), items=json.dumps(slim(items), ensure_ascii=False))


def to_markdown(plan, now):
    lines = [f"# Briefing {now:%Y-%m-%d}", ""]
    for r in RESSORT_ORDER:
        group = [c for c in plan["cluster"] if c["ressort"] == r]
        if not group:
            continue
        lines += [f"## {r}", ""]
        for c in group:
            lines.append(f"### {c['thema']} (Relevanz {c['relevanz']}, {c['quellen_anzahl']} Quellen: {', '.join(c['quellen'])})")
            lines += [f"- {f}" for f in c["kernfakten"]]
            if c["einordnung"]:
                lines.append(f"Einordnung: {c['einordnung']}")
            lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Prompt ausgeben, kein API-Aufruf")
    args = ap.parse_args()
    data = json.loads((OUT / "items.json").read_text(encoding="utf-8"))
    now = datetime.now(ZoneInfo(TIMEZONE))
    prompt = build_prompt(data["items"], now)
    if args.dry_run:
        print(prompt[:3000], f"\n... ({len(prompt)} Zeichen, ca. {len(prompt) // 4} Tokens)")
        return
    log.info("Modell %s, Prompt %d Zeichen", llm.model_name(), len(prompt))
    result = llm.generate(prompt, schema=Plan, temperature=0.2)
    plan = result.model_dump() if hasattr(result, "model_dump") else json.loads(result)
    plan["cluster"] = [c for c in plan["cluster"] if c["ressort"] in RESSORT_ORDER]
    (OUT / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "briefing.md").write_text(to_markdown(plan, now), encoding="utf-8")
    log.info("%d Cluster geschrieben", len(plan["cluster"]))


if __name__ == "__main__":
    main()
