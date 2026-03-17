# Fily

Ein schneller, übersichtlicher Dateiexplorer — gebaut mit Python und PySide6.
Läuft auf **macOS**, **Linux** und **Windows**.

---

## Features

- Detailansicht mit Name, Änderungsdatum, Größe, Typ
- Favoritenleiste (Drag & Drop zum Sortieren)
- Tab-basiertes Browsen (mehrere Ordner gleichzeitig)
- Vollständige Tastaturnavigation (Tab, Pfeiltasten, Alt+← / →)
- Kopieren, Ausschneiden, Einfügen mit Fortschrittsanzeige
- Umbenennen, Mehrfach-Umbenennen mit Muster (`{name}_{n:03d}{ext}`)
- Undo für Umbenennen, Verschieben, Kopieren, Neuer Ordner
- Versteckte Dateien ein-/ausblenden (wird gespeichert)
- Suche im aktuellen Ordner
- In Papierkorb legen (plattformübergreifend via `send2trash`)
- Liquid-Glass-Seitenleiste (Dark & Light Mode)
- Letzten Pfad beim nächsten Start wiederherstellen
- Open Source (MIT) · [Buy me a coffee ☕](https://buymeacoffee.com/buged86o)

---

## Voraussetzungen

| | Voraussetzung |
|---|---|
| Python | 3.13+ empfohlen |
| macOS | 12 Monterey oder neuer |
| Linux | X11 oder Wayland, `xdg-open` verfügbar |
| Windows | Windows 10 / 11 |

---

## Installation (Entwicklung)

```bash
git clone https://gitea.burkard3.ch/sascha/Fily.git
cd Fily

# Virtuelle Umgebung anlegen
python3 -m venv .venv

# Aktivieren
# macOS / Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Abhängigkeiten installieren
pip install -r requirements.txt

# Starten
python main.py
```

---

## App bauen (Distribution)

### macOS — `.app`

**Voraussetzungen:** Xcode Command Line Tools (`xcode-select --install`)

```bash
# Vorbereitung (einmalig)
chmod +x build_app.sh

# Build starten
./build_app.sh
```

→ Ergebnis: `dist/Fily.app`

**In Programme-Ordner installieren:**
```bash
cp -R "dist/Fily.app" /Applications/
```

**Optional: Code-Signierung** (nötig für Weitergabe außerhalb App Store)
```bash
codesign --deep --force --verify --verbose \
  --sign "Developer ID Application: Dein Name (TEAMID)" \
  "dist/Fily.app"
```

---

### Linux — Executable

**Voraussetzungen:** `python3-dev`, `libxcb-*` Pakete

```bash
# Ubuntu / Debian
sudo apt install python3-dev python3-venv libxcb-xinerama0

# Virtuelle Umgebung und Abhängigkeiten
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Build
pyinstaller OSX_Explorer.spec

# Starten
./dist/Fily/Fily
```

→ Ergebnis: `dist/Fily/` (Ordner mit Binary)

**Optional: Einzelne Binary erstellen**
```bash
pyinstaller OSX_Explorer.spec --onefile
# Binary: dist/Fily
```

**Desktop-Eintrag erstellen (systemweit):**
```bash
sudo cp dist/Fily/Fily /usr/local/bin/fily
sudo cp assets/icons/linux/256x256.png /usr/share/pixmaps/fily.png

# Desktop-Datei anlegen:
cat > ~/.local/share/applications/fily.desktop << EOF
[Desktop Entry]
Name=Fily
Exec=/usr/local/bin/fily
Icon=fily
Type=Application
Categories=Utility;FileManager;
EOF
```

---

### Windows — `.exe`

**Voraussetzungen:** Python 3.13 von python.org (mit `Add to PATH` aktiviert)

```powershell
# PowerShell (als normaler Benutzer)

# Virtuelle Umgebung
python -m venv .venv
.venv\Scripts\activate

# Abhängigkeiten
pip install -r requirements.txt

# Build
pyinstaller OSX_Explorer.spec

# Starten
dist\Fily\Fily.exe
```

→ Ergebnis: `dist\Fily\Fily.exe`

**Optional: Installer mit Inno Setup**
1. [Inno Setup](https://jrsoftware.org/isinfo.php) installieren
2. `installer.iss` anpassen (Pfad zur EXE eintragen)
3. Inno Setup Compiler ausführen → `.exe`-Installer

**Optional: Code-Signierung**
```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
  /f MeinZertifikat.pfx /p MeinPasswort `
  "dist\Fily\Fily.exe"
```

---

## Icon-Dateien

Alle Icons liegen bereits im Ordner `assets/icons/`:

```
assets/
└── icons/
    ├── master.png          ← 1024×1024 px, Quelldatei
    ├── macos/
    │   └── icon.icns       ← macOS App-Icon
    ├── windows/
    │   └── icon.ico        ← Windows App-Icon
    └── linux/
        ├── 16x16.png
        ├── 22x22.png
        ├── 24x24.png
        ├── 32x32.png
        ├── 48x48.png
        ├── 64x64.png
        ├── 128x128.png
        ├── 256x256.png
        └── 512x512.png
```

### macOS — `icon.icns` neu erstellen

```bash
mkdir icon.iconset
sips -z 16 16     assets/icons/master.png --out icon.iconset/icon_16x16.png
sips -z 32 32     assets/icons/master.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32     assets/icons/master.png --out icon.iconset/icon_32x32.png
sips -z 64 64     assets/icons/master.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128   assets/icons/master.png --out icon.iconset/icon_128x128.png
sips -z 256 256   assets/icons/master.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256   assets/icons/master.png --out icon.iconset/icon_256x256.png
sips -z 512 512   assets/icons/master.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512   assets/icons/master.png --out icon.iconset/icon_512x512.png
sips -z 1024 1024 assets/icons/master.png --out icon.iconset/icon_512x512@2x.png
iconutil -c icns icon.iconset -o assets/icons/macos/icon.icns
rm -rf icon.iconset
```

### Windows — `icon.ico` neu erstellen

```python
# ico_erstellen.py (einmalig ausführen)
from PIL import Image
img = Image.open("assets/icons/master.png")
img.save("assets/icons/windows/icon.ico",
         sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
```

### Linux — PNGs neu generieren

```bash
for size in 16 22 24 32 48 64 128 256 512; do
    sips -z $size $size assets/icons/master.png \
        --out assets/icons/linux/${size}x${size}.png
done
# Auf Linux statt sips: ImageMagick
# convert assets/icons/master.png -resize ${size}x${size} assets/icons/linux/${size}x${size}.png
```

---

## Lizenz

MIT License — kostenlos, Open Source, für jeden frei nutzbar.

Wenn dir Fily gefällt, freue ich mich über einen Kaffee:
**[☕ buymeacoffee.com/saschaburkard](https://buymeacoffee.com/buged86o)**

Quellcode: **[github.com/saschaburkard/fily](https://github.com/saschaburkard/fily)**

---

## Projektstruktur

```
Fily/
├── main.py                 # Hauptanwendung
├── requirements.txt        # Python-Abhängigkeiten
├── OSX_Explorer.spec       # PyInstaller-Konfiguration
├── build_app.sh            # Build-Script (macOS/Linux)
├── ROADMAP.md              # Entwicklungs-Roadmap
├── assets/
│   └── icons/
│       ├── master.png      # 1024×1024 Quelldatei
│       ├── macos/icon.icns
│       ├── windows/icon.ico
│       └── linux/*.png
└── .venv/                  # Virtuelle Umgebung (nicht im Repo)
```

---

## Abhängigkeiten

| Paket | Version | Zweck |
|-------|---------|-------|
| PySide6 | ≥ 6.10.2 | Qt6-UI-Framework |
| send2trash | ≥ 1.8.0 | Plattformübergreifender Papierkorb |
| pyinstaller | ≥ 6.0.0 | App-Kompilierung |
| pyobjc-framework-Cocoa | ≥ 12.1 | macOS-Integration (nur macOS) |
