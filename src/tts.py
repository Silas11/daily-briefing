"""Skript -> episode.mp3. edge-tts in Chunks, ffmpeg-Concat, Mono 80 kbit/s, Loudness-Normalisierung.

Fallback: Google Cloud TTS (REST, Free Tier), aktiv wenn GOOGLE_TTS_API_KEY gesetzt ist.
"""
import argparse
import asyncio
import base64
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import edge_tts
import requests

from common import CONFIG, OUT, get_logger, load_yaml, retry

log = get_logger("tts")
DEFAULT_VOICE = "de-DE-KatjaNeural"
DEFAULT_RATE = "+20%"  # 1,2-fache Geschwindigkeit, per Env TTS_RATE aenderbar
MAX_CHARS = 900
BITRATE = "80k"


def apply_pronunciation(text):
    try:
        repl = load_yaml("pronunciation.yaml") or {}
    except FileNotFoundError:
        return text
    for word, spoken in repl.items():
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", spoken, text)
    return text


def chunk(text, limit=MAX_CHARS):
    chunks = []
    for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
        if len(para) <= limit:
            chunks.append(para)
            continue
        cur = ""
        for sent in re.split(r"(?<=[.!?])\s+", para):
            if cur and len(cur) + len(sent) + 1 > limit:
                chunks.append(cur)
                cur = sent
            else:
                cur = f"{cur} {sent}".strip()
        if cur:
            chunks.append(cur)
    return chunks


@retry(attempts=4, base_delay=3)
def edge_chunk(text, voice, path):
    asyncio.run(edge_tts.Communicate(text, voice, rate=os.environ.get("TTS_RATE", DEFAULT_RATE)).save(str(path)))
    if Path(path).stat().st_size < 1000:
        raise RuntimeError("edge-tts lieferte leere Datei")


@retry(attempts=3, base_delay=3, exceptions=(requests.RequestException,))
def google_chunk(text, path):
    key = os.environ["GOOGLE_TTS_API_KEY"]
    body = {
        "input": {"text": text},
        "voice": {"languageCode": "de-DE", "name": os.environ.get("GOOGLE_TTS_VOICE", "de-DE-Neural2-F")},
        "audioConfig": {"audioEncoding": "MP3"},
    }
    r = requests.post(f"https://texttospeech.googleapis.com/v1/text:synthesize?key={key}", json=body, timeout=60)
    r.raise_for_status()
    Path(path).write_bytes(base64.b64decode(r.json()["audioContent"]))


def synth_chunk(text, voice, path):
    try:
        edge_chunk(text, voice, path)
        return "edge-tts"
    except Exception as ex:  # noqa: BLE001
        if not os.environ.get("GOOGLE_TTS_API_KEY"):
            raise
        log.warning("edge-tts ausgefallen (%s), Fallback Google Cloud TTS", ex)
        google_chunk(text, path)
        return "google"


def concat_encode(parts, out_path):
    with tempfile.TemporaryDirectory() as tmp:
        lst = Path(tmp) / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ac", "1", "-ar", "44100", "-b:a", BITRATE, str(out_path)],
            check=True,
        )


def duration_seconds(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def render(text, voice, out_path):
    text = apply_pronunciation(text)
    chunks = chunk(text)
    log.info("%d Chunks, Stimme %s", len(chunks), voice)
    with tempfile.TemporaryDirectory() as tmp:
        parts, engines = [], set()
        for i, c in enumerate(chunks):
            p = Path(tmp) / f"c{i:03d}.mp3"
            engines.add(synth_chunk(c, voice, p))
            parts.append(p)
        concat_encode(parts, out_path)
    dur = duration_seconds(out_path)
    log.info("%s: %.1f Minuten, %.1f MB, Engine %s", out_path.name, dur / 60, out_path.stat().st_size / 1e6, engines)
    return dur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", default=str(OUT / "script.txt"))
    ap.add_argument("--voice", default=os.environ.get("TTS_VOICE", DEFAULT_VOICE))
    ap.add_argument("--out", default=str(OUT / "episode.mp3"))
    args = ap.parse_args()
    text = Path(args.script).read_text(encoding="utf-8")
    dur = render(text, args.voice, Path(args.out))
    (OUT / "episode.json").write_text(json.dumps({"duration_seconds": round(dur)}), encoding="utf-8")


if __name__ == "__main__":
    main()
