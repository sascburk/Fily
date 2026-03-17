#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Fily — Build-Script
# Erstellt eine macOS .app mit PyInstaller
#
# Voraussetzungen:
#   • Python 3.11+ (empfohlen: via pyenv oder Homebrew)
#   • Homebrew (optional, für pyenv)
#
# Verwendung:
#   chmod +x build_app.sh
#   ./build_app.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "────────────────────────────────────────────"
echo "  Fily — Build"
echo "────────────────────────────────────────────"

# ── 1. Virtuelle Umgebung anlegen ─────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "▶ Erstelle virtuelle Python-Umgebung …"
    python3 -m venv .venv
fi

echo "▶ Aktiviere virtuelle Umgebung …"
source .venv/bin/activate

# ── 2. Abhängigkeiten installieren ────────────────────────────────────────────
echo "▶ Installiere/aktualisiere Abhängigkeiten …"
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# ── 3. Alte Build-Artefakte aufräumen ─────────────────────────────────────────
echo "▶ Räume alte Build-Artefakte auf …"
rm -rf build dist

# ── 4. PyInstaller ausführen ──────────────────────────────────────────────────
echo "▶ Baue .app mit PyInstaller …"
pyinstaller OSX_Explorer.spec

# ── 5. Ergebnis prüfen ────────────────────────────────────────────────────────
APP="dist/Fily.app"
if [ -d "$APP" ]; then
    echo ""
    echo "✅  Build erfolgreich!"
    echo "    App:  $SCRIPT_DIR/$APP"
    echo ""
    echo "    Zum Installieren die .app in den Programme-Ordner ziehen:"
    echo "    cp -R \"$APP\" /Applications/"
    echo ""

    # Optional: App sofort öffnen
    read -r -p "App jetzt starten? [j/N] " ans
    if [[ "$ans" =~ ^[jJ]$ ]]; then
        open "$APP"
    fi
else
    echo "❌  Build fehlgeschlagen. Prüfe die Ausgabe oben."
    exit 1
fi
