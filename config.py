"""
config.py — Konstanten, Pfade und Hilfsfunktionen für Fily.
Wird von allen anderen Modulen importiert.
"""
import sys
from pathlib import Path

# ── App-Identität ─────────────────────────────────────────────────────────────
APP_NAME   = "Fily"
ORG_NAME   = "Fily"
VERSION    = "2.0.8"

# URLs
BUYMEACOFFEE_URL = "https://buymeacoffee.com/buged86o"
GITHUB_URL       = "https://github.com/sascburk/fily"

# ── Konfigurationspfade ───────────────────────────────────────────────────────
CONFIG_DIR = Path.home() / ".config" / "fily"
FAV_FILE   = CONFIG_DIR / "favorites.json"

# Standard-Favoriten, die beim ersten Start angelegt werden
DEFAULT_FAVORITES = [
    {"name": "Home",      "path": str(Path.home())},
    {"name": "Desktop",   "path": str(Path.home() / "Desktop")},
    {"name": "Documents", "path": str(Path.home() / "Documents")},
    {"name": "Downloads", "path": str(Path.home() / "Downloads")},
    {"name": "Pictures",  "path": str(Path.home() / "Pictures")},
    {"name": "Music",     "path": str(Path.home() / "Music")},
    {"name": "Movies",    "path": str(Path.home() / "Movies")},
]

# ── QSettings-Schlüssel ───────────────────────────────────────────────────────
# Alle Schlüssel an einem Ort, um Tippfehler zu vermeiden.
SK_GEOMETRY        = "geometry"
SK_SPLITTER_MAIN   = "splitter/main"
SK_SPLITTER_PANE   = "splitter/pane"
SK_PREVIEW_VISIBLE = "preview/visible"
SK_PREVIEW_WIDTH   = "preview/width"
SK_COL_WIDTHS      = "columns/widths"      # JSON-Array [w0,w1,w2,w3]
SK_COL_SORT_COL    = "columns/sort_col"
SK_COL_SORT_ORDER  = "columns/sort_order"
SK_VIEW_MODE       = "view/mode"           # "list" | "icon"
SK_LAST_PATH       = "last_path"
SK_SHOW_HIDDEN     = "show_hidden"
SK_FDA_HINT        = "fda_hint_shown"
SK_FAV_BG_COLOR    = "favorites/bg_color"


def asset_path(*parts: str) -> Path:
    """Löst einen Pfad innerhalb von assets/ auf.

    Funktioniert sowohl im Quellcode-Modus (neben main.py) als auch in
    einem PyInstaller-Bundle (sys._MEIPASS enthält die entpackten Dateien).
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base.joinpath(*parts)
