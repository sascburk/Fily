"""
logger.py — Einfaches Datei-Logging für Laufzeitfehler.
"""
from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path

from config import CONFIG_DIR


LOG_DIR = CONFIG_DIR / "logs"
LOG_FILE = LOG_DIR / "fily.log"


def log_line(message: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")
    except Exception:
        # Logging darf die App niemals abbrechen.
        pass


def log_exception(exc: BaseException, context: str = "") -> None:
    prefix = f"{context}: " if context else ""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
    log_line(f"{prefix}{tb}")
