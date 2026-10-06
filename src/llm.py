"""Duenner Gemini-Wrapper mit Retry bei 429/5xx und Ausweichmodell.

Env: GEMINI_API_KEY, GEMINI_MODEL (Default gemini-3.8-flash), GEMINI_FALLBACK_MODELS (kommagetrennt, siehe DEFAULT_FALLBACKS).
"""
import os

from google import genai
from google.genai import errors, types

from common import get_logger, retry

log = get_logger("llm")
DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_FALLBACKS = "gemini-3.6-flash,gemini-3.5-flash,gemini-flash-latest,gemini-3.5-flash-lite,gemini-3.1-flash-lite"


def model_name():
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)


def _client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY fehlt (Env-Variable bzw. Repo-Secret).")
    return genai.Client(api_key=key)


class QuotaExhausted(Exception):
    """Tageskontingent des Modells aufgebraucht, kein Retry sinnvoll."""


def _transient(ex):
    return isinstance(ex, errors.APIError) and (ex.code == 429 or (ex.code or 0) >= 500)


@retry(attempts=2, base_delay=6, exceptions=(errors.ServerError, errors.ClientError))
def _call(model, prompt, cfg):
    client = _client()  # Referenz halten, sonst schliesst der GC den HTTP-Client
    try:
        return client.models.generate_content(model=model, contents=prompt, config=types.GenerateContentConfig(**cfg))
    except errors.APIError as ex:
        if ex.code == 429 and "PerDay" in str(ex):
            raise QuotaExhausted(model) from ex
        if not _transient(ex):
            raise SystemExit(f"Gemini-Fehler {ex.code} bei {model}: {ex.message}") from ex
        raise


def generate(prompt, schema=None, temperature=0.4):
    cfg = {"temperature": temperature, "automatic_function_calling": {"disable": True}}
    if schema is not None:
        cfg["response_mime_type"] = "application/json"
        cfg["response_schema"] = schema
    models = [model_name()]
    for fb in os.environ.get("GEMINI_FALLBACK_MODELS", DEFAULT_FALLBACKS).split(","):
        if fb.strip() and fb.strip() not in models:
            models.append(fb.strip())
    last = None
    for m in models:
        try:
            resp = _call(m, prompt, cfg)
            if m != models[0]:
                log.warning("Ausweichmodell %s verwendet", m)
            return resp.parsed if schema is not None and resp.parsed is not None else resp.text
        except QuotaExhausted:
            log.warning("Tageskontingent von %s erschoepft, naechstes Modell", m)
            last = f"Kontingent {m}"
        except (errors.ServerError, errors.ClientError) as ex:
            log.error("Modell %s nach Retries erfolglos: %s", m, ex)
            last = ex
    raise SystemExit(f"Alle Modelle erfolglos: {last}")
