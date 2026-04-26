#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Fily — Build-Script (PyInstaller)
#
# Ausgabe plattformabhängig (siehe fily_app.spec):
#   • macOS:   dist/Fily.app
#   • Linux:   dist/Fily   (ausführbare Datei)
#   • Windows: dist/Fily.exe
#
# Voraussetzungen:
#   • Python 3.11+ (venv empfohlen)
#   • macOS: optional Homebrew/pyenv
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
if [ -d dist ] && [ -n "$(ls -A dist 2>/dev/null)" ]; then
    echo "▶ Im Ordner „dist“ liegen bereits Dateien oder Unterordner:"
    ls -la dist
    echo ""
    read -r -p "Diese löschen und neu bauen? [j/N] " _dist_ans
    if [[ ! "$_dist_ans" =~ ^[jJ]$ ]]; then
        echo "Abgebrochen (dist unverändert)."
        exit 0
    fi
fi
echo "▶ Räume alte Build-Artefakte auf …"
rm -rf build dist

# ── 4. PyInstaller ausführen ──────────────────────────────────────────────────
case "$(uname -s)" in
    Darwin) echo "▶ Baue macOS-Bundle mit PyInstaller …" ;;
    Linux)  echo "▶ Baue Linux-Binary mit PyInstaller …" ;;
    MINGW*|MSYS*|CYGWIN*) echo "▶ Baue Windows-EXE mit PyInstaller …" ;;
    *)      echo "▶ Baue mit PyInstaller …" ;;
esac
pyinstaller fily_app.spec

# ── 5. Ergebnis prüfen (Spec liefert je nach OS unterschiedliche Artefakte) ───
ARTIFACT=""
HINT=""
case "$(uname -s)" in
    Darwin)
        ARTIFACT="dist/Fily.app"
        if [ -d "$ARTIFACT" ]; then
            HINT="Zum Installieren: cp -R \"$ARTIFACT\" /Applications/"
        fi
        ;;
    Linux)
        ARTIFACT="dist/Fily"
        if [ -f "$ARTIFACT" ]; then
            HINT="Starten: \"$SCRIPT_DIR/$ARTIFACT\""
        fi
        ;;
    MINGW*|MSYS*|CYGWIN*)
        ARTIFACT="dist/Fily.exe"
        if [ -f "$ARTIFACT" ]; then
            HINT="Starten: \"$SCRIPT_DIR/$ARTIFACT\""
        fi
        ;;
    *)
        ARTIFACT="dist/Fily.app"
        if [ -d "$ARTIFACT" ]; then
            HINT="macOS-Bundle: $ARTIFACT"
        else
            ARTIFACT="dist/Fily"
            [ -f "$ARTIFACT" ] && HINT="Binary: $ARTIFACT"
        fi
        ;;
esac

if [ -n "$ARTIFACT" ] && { [ -d "$ARTIFACT" ] || [ -f "$ARTIFACT" ]; }; then
    echo ""
    echo "✅  Build erfolgreich!"
    echo "    Artefakt:  $SCRIPT_DIR/$ARTIFACT"
    [ -n "$HINT" ] && echo "    $HINT"
    echo ""

    read -r -p "Jetzt starten? [j/N] " ans
    if [[ "$ans" =~ ^[jJ]$ ]]; then
        case "$(uname -s)" in
            Darwin) open "$ARTIFACT" ;;
            Linux)  "$SCRIPT_DIR/$ARTIFACT" & ;;
            MINGW*|MSYS*|CYGWIN*) cmd //c start "" "$ARTIFACT" ;;
        esac
    fi
else
    echo "❌  Build fehlgeschlagen. Erwartet wurde u. a. dist/Fily.app (macOS) oder dist/Fily (Linux)."
    echo "    Prüfe die PyInstaller-Ausgabe und build/*/warn-*.txt"
    exit 1
fi
