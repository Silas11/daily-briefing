"""Skript -> episode.mp3.

Hauptengine: Gemini-TTS (Stimme Kore, Stilanweisung als Regieblock). Fallback: edge-tts (Katja, 1,2-fach),
danach optional Google Cloud TTS. Chunking, ffmpeg-Concat, Mono, Loudness-Normalisierung.
Env: TTS_ENGINE (gemini|edge), GEMINI_TTS_VOICE, GEMINI_TTS_MODELS, TTS_RATE, TTS_VOICE.
"""
import argparse
import asyncio
import base64
import json
import os
import re
import subprocess
import time
import tempfile
import wave
from pathlib import Path

import edge_tts
import requests
from google import genai
from google.genai import errors, types

from common import CONFIG, OUT, get_logger, load_yaml, retry

log = get_logger("tts")
DEFAULT_VOICE = "de-DE-KatjaNeural"
DEFAULT_RATE = "+20%"  # 1,2-fache Geschwindigkeit, per Env TTS_RATE aenderbar
MAX_CHARS = 900
BITRATE = "80k"
GEMINI_MODELS = "gemini-3.8-flash-tts,gemini-3.1-flash-tts-preview,gemini-3.8-flash-lite-tts"
GEMINI_VOICE = "Kore"
GEMINI_CHUNK_CHARS = 2400
PAUSE_MS = 600
DIRECTOR = (
    "# AUDIO PROFILE\nProfessioneller deutscher Nachrichtensprecher eines Morgen-Podcasts.\n\n"
    "## DIRECTOR'S NOTES\nStil: warm, klar, souveraen, wie ein erfahrener Radiojournalist. Lebendige Betonung, natuerliche Satzmelodie, "
    "kleine Pausen an Satzenden und zwischen Absaetzen. Nicht monoton, nicht uebertrieben.\nTempo: zuegig, etwa 1,15-fach.\n\n"
    "#### TRANSCRIPT\n"
)


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


class GeminiTTSFailed(Exception):
    pass


def gemini_chunk(text, voice, models, path):
    """Erzeugt eine WAV-Datei (24 kHz mono) mit Pause am Ende. Probiert die Modelle der Reihe nach."""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=types.HttpOptions(timeout=240_000))
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
    )
    last = None
    for model in models:
        for attempt in range(2):
            try:
                r = client.models.generate_content(model=model, contents=DIRECTOR + text, config=cfg)
                parts = r.candidates[0].content.parts if r.candidates and r.candidates[0].content else None
                pcm = parts[0].inline_data.data if parts and parts[0].inline_data else None
                if not pcm or len(pcm) < 24000:
                    raise RuntimeError("keine Audiodaten")
                with wave.open(str(path), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(24000)
                    w.writeframes(pcm + b"\x00\x00" * int(24000 * PAUSE_MS / 1000))
                return model
            except errors.APIError as ex:
                last = ex
                if ex.code == 429 and "PerDay" in str(ex):
                    log.warning("Tageskontingent von %s erschoepft", model)
                    break
                log.warning("%s Versuch %d: %s", model, attempt + 1, str(ex)[:100])
                time.sleep(5 * (attempt + 1))
            except Exception as ex:  # noqa: BLE001
                last = ex
                log.warning("%s Versuch %d: %s", model, attempt + 1, str(ex)[:100])
                time.sleep(5)
    raise GeminiTTSFailed(str(last))


def gemini_chunks(text, limit=GEMINI_CHUNK_CHARS):
    """Gruppiert ganze Absaetze zu Bloecken bis limit Zeichen, damit die Satzmelodie je Block zusammenhaengt."""
    out, cur = [], ""
    for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
        if cur and len(cur) + len(para) + 2 > limit:
            out.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}".strip()
    if cur:
        out.append(cur)
    return out


def render_gemini(text, out_path):
    voice = os.environ.get("GEMINI_TTS_VOICE", GEMINI_VOICE)
    models = [m.strip() for m in os.environ.get("GEMINI_TTS_MODELS", GEMINI_MODELS).split(",") if m.strip()]
    chunks = gemini_chunks(text)
    log.info("Gemini-TTS: %d Bloecke, Stimme %s", len(chunks), voice)
    with tempfile.TemporaryDirectory() as tmp:
        parts, used = [], set()
        for i, c in enumerate(chunks):
            p = Path(tmp) / f"c{i:03d}.wav"
            used.add(gemini_chunk(c, voice, models, p))
            parts.append(p)
            log.info("Block %d/%d fertig", i + 1, len(chunks))
        concat_encode(parts, out_path)
    return f"gemini:{'+'.join(sorted(used))}"


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
    if os.environ.get("TTS_ENGINE", "gemini") == "gemini":
        try:
            engine = render_gemini(text, out_path)
            dur = duration_seconds(out_path)
            log.info("%s: %.1f Minuten, %.1f MB, Engine %s", out_path.name, dur / 60, out_path.stat().st_size / 1e6, engine)
            return dur
        except GeminiTTSFailed as ex:
            log.error("Gemini-TTS ausgefallen (%s), Fallback edge-tts", str(ex)[:120])
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
