# Fily 🗂️

A fast, clean file explorer built with Python and PySide6.
Because Finder is nice, but sometimes you just want something that *works*.
Runs on **macOS**, **Linux** and **Windows** — yes, all three. We're not picky.

---

## Features

- Detail view with name, date, size, and type (the boring but important stuff)
- Favorites sidebar — drag & drop to sort, because order matters
- Tab-based browsing — juggle multiple folders like a pro
- Full keyboard navigation (Tab, arrow keys, Alt+← / →) — mouse optional
- Copy, cut, paste with progress bar — so you know it's actually doing something
- Rename & batch rename with patterns (`{name}_{n:03d}{ext}`) — nerd mode activated
- Undo for rename, move, copy, new folder — because mistakes happen
- Toggle hidden files — your `.secrets` are safe with us
- Search in current folder — find that file you *definitely* saved somewhere
- Trash support via `send2trash` — cross-platform and guilt-free deletion
- Liquid-glass sidebar (Dark & Light Mode) — looks good, works good
- Restores last path on startup — picks up right where you left off
- Open Source (MIT) · [Buy me a coffee ☕](https://buymeacoffee.com/buged86o)

---

## Requirements

| | Requirement |
|---|---|
| Python | 3.13+ recommended |
| macOS | 12 Monterey or newer |
| Linux | X11 or Wayland, `xdg-open` available |
| Windows | Windows 10 / 11 |

---

## Installation (Development)

```bash
git clone https://github.com/saschaburkard/fily.git
cd fily

# Create virtual environment
python3 -m venv .venv

# Activate it
# macOS / Linux:
source .venv/bin/activate
# Windows (yes, the backslash is intentional):
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

---

## Build (Distribution)

### macOS — `.app`

**Requirements:** Xcode Command Line Tools (`xcode-select --install`)

```bash
chmod +x build_app.sh
./build_app.sh
```

→ Result: `dist/Fily.app`

**Install to Applications:**
```bash
cp -R "dist/Fily.app" /Applications/
```

**Optional: Code signing** (needed if you want to share it without scary warnings)
```bash
codesign --deep --force --verify --verbose \
  --sign "Developer ID Application: Your Name (TEAMID)" \
  "dist/Fily.app"
```

---

### Linux — Executable

**Requirements:** `python3-dev`, `libxcb-*` packages

```bash
# Ubuntu / Debian
sudo apt install python3-dev python3-venv libxcb-xinerama0

# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Build
pyinstaller fily_app.spec

# Run
./dist/Fily/Fily
```

→ Result: `dist/Fily/` folder with binary

**Optional: Desktop entry**
```bash
sudo cp dist/Fily/Fily /usr/local/bin/fily
sudo cp assets/icons/linux/256x256.png /usr/share/pixmaps/fily.png

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

**Requirements:** Python 3.13 from python.org (check "Add to PATH" — seriously, check it)

```powershell
# PowerShell

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Build
pyinstaller fily_app.spec

# Run
dist\Fily\Fily.exe
```

→ Result: `dist\Fily\Fily.exe`

**Optional: Installer with Inno Setup**
1. Install [Inno Setup](https://jrsoftware.org/isinfo.php)
2. Edit `installer.iss` (point it to your EXE)
3. Run Inno Setup Compiler → shiny `.exe` installer

**Optional: Code signing** (prevents Windows Defender from having a meltdown)
```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
  /f MyCert.pfx /p MyPassword `
  "dist\Fily\Fily.exe"
```

---

## Icons

All icons are already in `assets/icons/` — nothing to do here, just enjoy:

```
assets/
└── icons/
    ├── master.png          ← 1024×1024 px source file
    ├── macos/
    │   └── icon.icns
    ├── windows/
    │   └── icon.ico
    └── linux/
        ├── 16x16.png  22x22.png  24x24.png  32x32.png
        ├── 48x48.png  64x64.png  128x128.png
        ├── 256x256.png  512x512.png
```

**Regenerate macOS icon:**
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

**Regenerate Windows icon:**
```python
from PIL import Image
img = Image.open("assets/icons/master.png")
img.save("assets/icons/windows/icon.ico",
         sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
```

---

## License

MIT — free as in freedom, free as in beer.
Do whatever you want with it. Attribution appreciated, but not enforced by lawyers.

If Fily saves you time (or just makes you smile), consider buying me a coffee:
**[☕ buymeacoffee.com/buged86o](https://buymeacoffee.com/buged86o)**

No subscription. No upsell. Just coffee. ☕

---

## Project Structure

```
fily/
├── main.py                 # The whole app lives here
├── requirements.txt        # Python dependencies
├── fily_app.spec       # PyInstaller config
├── build_app.sh            # Build script (macOS/Linux)
├── assets/
│   └── icons/
│       ├── master.png
│       ├── macos/icon.icns
│       ├── windows/icon.ico
│       └── linux/*.png
└── .venv/                  # Virtual environment (not in repo, obviously)
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| PySide6 | ≥ 6.10.2 | Qt6 UI framework — the engine |
| send2trash | ≥ 1.8.0 | Cross-platform trash — no regrets |
| pyinstaller | ≥ 6.0.0 | Turns Python into a real app |
| pyobjc-framework-Cocoa | ≥ 12.1 | macOS magic (macOS only) |

---

## Keyboard Shortcuts

Full list available in the app under **Help → Keyboard Shortcuts**.

| Action | macOS | Linux / Windows |
|--------|-------|-----------------|
| Open folder | Enter / Double-click | Enter / Double-click |
| Go back | Alt+← | Alt+← |
| Go forward | Alt+→ | Alt+→ |
| Parent folder | Alt+↑ / Backspace | Alt+↑ / Backspace |
| Focus address bar | Cmd+L / F4 | Ctrl+L / F4 |
| Focus search | Cmd+F | Ctrl+F |
| New tab | Cmd+T | Ctrl+T |
| Close tab | Cmd+W | Ctrl+W |
| Next tab | Cmd+Shift+→ | Ctrl+Tab |
| Previous tab | Cmd+Shift+← | Ctrl+Shift+Tab |
| Refresh | F5 | F5 |
| Select all | Cmd+A | Ctrl+A |
| Cycle items | Tab / Shift+Tab | Tab / Shift+Tab |
| Copy | Cmd+C | Ctrl+C |
| Cut | Cmd+X | Ctrl+X |
| Paste | Cmd+V | Ctrl+V |
| Rename | F2 | F2 |
| Move to trash | Cmd+Backspace | Delete |
| Undo | Cmd+Z | Ctrl+Z |
| New folder | Cmd+N | Ctrl+N |
| Quit | Cmd+Q | Ctrl+Q |

---

## Contributing

Found a bug? Have an idea? PRs are welcome.
Open an issue, fork it, fix it, ship it. The usual open source dance. 🕺
