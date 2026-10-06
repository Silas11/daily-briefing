"""Gemeinsame Helfer: Pfade, Config, Logging, Retry."""
import functools
import logging
import os
import random
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
OUT = ROOT / "out"
PROMPTS = ROOT / "prompts"
DOCS = ROOT / "docs"

USER_AGENT = "Mozilla/5.0 (compatible; daily-briefing/0.1; personal-use)"
TIMEZONE = "Europe/Berlin"

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def get_logger(name):
    return logging.getLogger(name)


def load_yaml(name):
    with open(CONFIG / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_out():
    OUT.mkdir(exist_ok=True)
    return OUT


def retry(attempts=4, base_delay=2.0, exceptions=(Exception,)):
    """Exponentielles Backoff mit Jitter."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            log = get_logger(fn.__name__)
            for i in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as ex:
                    if i == attempts - 1:
                        raise
                    delay = base_delay * (2**i) + random.uniform(0, 1)
                    log.warning("Versuch %d/%d fehlgeschlagen (%s), neuer Versuch in %.1fs", i + 1, attempts, ex, delay)
                    time.sleep(delay)

        return wrapper

    return deco
