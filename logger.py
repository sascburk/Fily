"""
logger.py — Einfaches Datei-Logging für Laufzeitfehler.
"""
from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings

from config import CONFIG_DIR, ORG_NAME, SK_DEBUG_ENABLED


LOG_DIR = CONFIG_DIR / "logs"
LOG_FILE = LOG_DIR / "fily.log"


def is_debug_enabled() -> bool:
    s = QSettings(ORG_NAME, "Debug")
    return s.value(SK_DEBUG_ENABLED, False, type=bool)


def set_debug_enabled(enabled: bool) -> None:
    s = QSettings(ORG_NAME, "Debug")
    s.setValue(SK_DEBUG_ENABLED, bool(enabled))
    log_line_force(f"Debug mode {'enabled' if enabled else 'disabled'}")


def log_line(message: str) -> None:
    if not is_debug_enabled():
        return
    _write_line(message)


def log_line_force(message: str) -> None:
    _write_line(message)


def _write_line(message: str) -> None:
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
    log_line_force(f"{prefix}{tb}")
