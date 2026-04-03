# Fily 2.0 — Design Spec

**Datum:** 2026-04-03  
**Status:** Zur Implementierung freigegeben  
**Plattformen:** macOS · Windows · Linux  
**Kompilierung:** PyInstaller `--onefile` (Windows & Linux), `.app`-Bundle (macOS)

---

## 1. Ziel

Fily wird von einer einzelnen ~1990-Zeilen-Datei in eine saubere Modulstruktur aufgeteilt.
Gleichzeitig werden alle bekannten Bugs behoben und zehn neue Features ergänzt.
Das Layout wechselt auf **Layout C**: Tabs als primäre Navigationsstruktur,
optionaler Split (F8) und optionaler Vorschau-Drawer (F9).

---

## 2. Modulstruktur

**Flache Struktur** (alle Dateien auf gleicher Ebene, kein Python-Package) —
optimiert für PyInstaller `--onefile`. Imports lauten `from config import ...`.

```
main.py          # Einstiegspunkt: main(), Plattform-Setup
config.py        # Konstanten, QSettings-Schlüssel, Pfade, _asset_path()
models.py        # FavoritesModel, ExplorerModel (QFileSystemModel)
workers.py       # UndoStack, CopyWorker (QThread)
fileops.py       # _do_copy, _do_move, trash, archive (ZIP/TAR)
dialogs.py       # BatchRenameDialog, ShortcutsDialog, AboutDialog, PropertiesDialog
browser.py       # FileBrowser-Widget (Inhalt eines Tabs)
mainwindow.py    # MainWindow: Split-Tabs, Menü, Shortcuts, Preview-Drawer
favorites.py     # FavoritesPanel (Liquid-Glass, größere Schrift als Dateiliste)
addressbar.py    # BreadcrumbBar + Textfeld (umschaltbar per Doppelklick)
treeview.py      # ExplorerTreeView (D&D rein + raus), IconView
preview.py       # PreviewDrawer (Bild / Text / Metadaten)
toolbar.py       # Moderne Toolbar mit SVG-Icons
assets/          # Icons, SVGs (über _asset_path() aufgelöst)
```

`_asset_path(rel)` in `config.py`: löst `sys._MEIPASS/rel` (PyInstaller-Freeze)
oder `__file__`-Verzeichnis auf — funktioniert in beiden Modi.

---

## 3. Layout

### 3.1 Fensterbereiche (von links nach rechts)

```
┌─────────────────────────────────────────────────────────────────┐
│  Favoriten  │  [Tab 1 ✕] [Tab 2 ✕] [+]  ║  [Tab A ✕] [+]  │▶│ │
│  (kein      │─────────────────────────────╫──────────────────┤ │ │
│  Bereich    │  Toolbar (zurück/vor/hoch)  ║  Toolbar          │ │ │
│  darüber)   │  Breadcrumb-Adressleiste    ║  Breadcrumb       │P│ │
│             │─────────────────────────────╫──────────────────┤r│ │
│  🏠 Home    │  Dateiliste / Icon-Raster   ║  Dateiliste       │e│ │
│  📁 Dokum.  │                             ║                   │v│ │
│  ⬇ Downl.  │                             ║                   │i│ │
│  🖼 Bilder  │                             ║                   │e│ │
│             │                             ║                   │w│ │
│─────────────┴─────────────────────────────╨───────────────────┤ │ │
│  Statusleiste: N ausgewählt · M Elemente · 💾 234 GB frei     │◀│ │
└─────────────────────────────────────────────────────────────────┘
```

- **Favoritenleiste:** Beginnt am absoluten oberen Fensterrand (kein Menü/Toolbar darüber).
  Schriftgröße der Einträge: **13 pt** (Dateiliste: 11 pt).
- **Tabs:** Labels befinden sich **über** den Tab-Inhalten (Qt-Standard `North`).
- **Split (F8):** Teilt den Browser-Bereich in zwei unabhängige Tab-Gruppen.
  Linke Gruppe ist immer sichtbar; rechte wird per F8 ein-/ausgeblendet.
  Beide Gruppen teilen sich **keine** Tabs — jede hat ihren eigenen Tab-Stack.
- **Vorschau-Drawer (F9):** Ausklappbarer Bereich am rechten Rand.
  Zeigt Bild-Vorschau, Text-Inhalt oder Metadaten des selektierten Elements.
  Breite ist einstellbar und wird per QSettings gespeichert.
- **Menüleiste:** Über der gesamten Fensterbreite (über Favoriten + Browser).
  Ausnahme macOS: native Menüleiste — kein Menü im Fenster sichtbar.

### 3.2 Keyboard-Shortcuts

| Kürzel | Aktion |
|--------|--------|
| F8 | Split-Pane ein-/ausschalten |
| F9 | Vorschau-Drawer ein-/ausschalten |
| Space | Vorschau-Drawer (Kurzform) |
| Cmd/Ctrl+T | Neuer Tab (aktive Gruppe) |
| Cmd/Ctrl+W | Tab schließen |
| Cmd/Ctrl+Z | Rückgängig |
| Cmd/Ctrl+C | Kopieren |
| Cmd/Ctrl+X | Ausschneiden |
| Cmd/Ctrl+V | Einfügen |
| F2 | Umbenennen |
| Del / Backspace | In Papierkorb |
| Cmd/Ctrl+N | Neuer Ordner |
| Cmd/Ctrl+A | Alles auswählen |
| Cmd/Ctrl+F | Suche (rekursiv) |

---

## 4. Features

### 4.1 Neue Features (alle implementieren)

#### F1 — Vorschau-Panel (PreviewDrawer)
- Rechter Rand, per F9 / Space ein-/ausklappbar.
- Zeigt: Bild-Thumbnail (skaliert), Text-Inhalt (erste 4 KB), Video-Thumbnail via
  `QMediaPlayer` falls verfügbar, sonst Datei-Icon.
- Metadatenzeile darunter: Größe, MIME-Typ, Änderungsdatum, Auflösung (bei Bildern).
- Zustand (offen/geschlossen, Breite) per QSettings gespeichert.

#### F2 — Breadcrumb-Adressleiste
- Klickbare Pfad-Segmente: `Home › Dokumente › Projekte`.
- Doppelklick auf Segment oder Klick auf leeren Bereich: Wechsel in Textfeld-Modus.
- Escape: zurück zu Breadcrumbs (ohne Navigation).
- Enter im Textfeld: navigiert zum eingegebenen Pfad.

#### F3 — Dual-Pane (Split-Tab-View)
- F8 aktiviert/deaktiviert den rechten Tab-Stack.
- Drag & Drop zwischen linkem und rechtem Browser: Kopieren (mit Ctrl) oder Verschieben.
- Beide Panes haben eigene Navigation, Tabs und Undo-History.
- Splitter-Position per QSettings gespeichert.

#### F4 — Rekursive Suche
- Cmd/Ctrl+F öffnet Suchleiste über der Dateiliste.
- Suche in allen Unterordnern des aktuellen Verzeichnisses.
- Ergebnisse erscheinen im selben Tab (in-place, kein neuer Tab).
- Abbruch-Schaltfläche für laufende Suche; läuft in QThread.

#### F5 — Disk-Space in Statusleiste
- `shutil.disk_usage()` des aktuellen Laufwerks.
- Format: `💾 Macintosh HD — 234 GB frei von 500 GB`.
- Aktualisierung beim Ordnerwechsel.

#### F6 — Icon-/Thumbnail-Ansicht
- Umschalter in Toolbar: Liste ↔ Icon-Raster.
- Icon-Raster: `QListView` im `IconMode`, Thumbnails per `QImageReader` (async).
- Zustand (welche Ansicht) per QSettings gespeichert.

#### F7 — „Öffnen mit…" im Kontextmenü
- macOS: `NSWorkspace.URLsForApplicationsToOpenURL` via `subprocess` / pyobjc.
- Windows: Registry-Lookup `HKEY_CLASSES_ROOT`.
- Linux: `xdg-mime query default` + `~/.local/share/applications/`.
- Fallback: Systemdialog (Qt `QDesktopServices.openUrl` reicht als letzter Ausweg).

#### F8 — ZIP / Archive
- Rechtsklick → „Als ZIP komprimieren": `zipfile.ZipFile` in CopyWorker-Thread.
- Rechtsklick → „Hier entpacken": `zipfile` / `tarfile` je nach Endung.
- Fortschrittsanzeige über bestehenden ProgressDialog.

#### F9 — Spalten & Sortierung global speichern
- Spaltenbreiten (Name, Datum, Größe, Art) per `QHeaderView.sectionSize()`.
- Sortier-Spalte und -Richtung (`sortColumn()`, `sortIndicatorOrder()`).
- Gespeichert als **eine globale Einstellung** (nicht pro Ordner) in QSettings.
- Wiederherstellung beim Start bevor erster Ordner geladen wird.

#### F10 — Modernere Toolbar
- SVG-Icons (oder Qt-Standard-Icons als Fallback).
- Schaltflächen: Zurück, Vor, Hoch, Neuer Ordner, Ansicht wechseln.
- Kompakter Modus: nur Icons ohne Text.

---

## 5. Bug-Fixes

### B1 — D&D Drop-Zone zu eng
**Problem:** `ExplorerTreeView.dragMoveEvent` lehnt Drops ab, wenn kein
Unterordner unter dem Cursor liegt — Ablegen auf die leere Fläche schlägt fehl.  
**Fix:** Wenn kein gültiges Drop-Ziel unter dem Cursor → Drop-Ziel = aktueller Ordner
(`self._current_path`). `dropEvent` sendet dann den richtigen Zielordner.

### B2 — Paste ignoriert System-Clipboard
**Problem:** `_paste()` liest nur internen `_clip_paths`-Buffer.  
**Fix:** Wenn `_clip_paths` leer → `QApplication.clipboard().mimeData().urls()`
auslesen → Liste von lokalen Pfaden extrahieren → als Kopier-Operation ausführen.

### B3 — Trash-Fallback ohne Warnung
**Problem:** `send2trash`-Fehler führt zu stillem permanentem Löschen.  
**Fix:** Bei `send2trash`-Exception → `QMessageBox.warning()` mit Text
„Papierkorb nicht verfügbar — Dateien permanent löschen?" → Nur bei Bestätigung
fortfahren.

### B4 — Spaltenbreiten nicht gespeichert  
→ Behoben durch Feature F9.

### B5 — Sortierung nicht gespeichert  
→ Behoben durch Feature F9.

### B6 — dconf binary parsing fragil (Linux)
**Fix:** Primär `gsettings get org.gnome.desktop.interface color-scheme` verwenden.
Binär-Parsing nur als letzten Fallback, mit Try/Except und Default `False`.

---

## 6. Bestehende Features (erhalten + verbessert)

- **Drag & Drop intern:** Dateien per D&D in Unterordner — bleibt erhalten.
- **Drag & Drop extern (aus Finder/Explorer → Fily):** Fix B1 behebt Drop auf leere Fläche.
- **Drag & Drop extern (aus Fily → andere App):** `startDrag()` mit
  `QMimeData.setUrls()` — bereits vorhanden, wird verifiziert.
- **Tab Tear-Off:** `TearOffTabBar` bleibt erhalten; wird in neue Modulstruktur übernommen.
- **Background-Copy-Worker:** `CopyWorker(QThread)` bleibt; wird um ZIP-Support erweitert.
- **Undo-Stack:** 50-Einträge, alle Operationen — bleibt erhalten.
- **Dark/Light Mode:** Automatische Erkennung + `_apply_dark_palette()` — bleibt.
- **Tastaturnavigation:** Vollständige Keyboard-Navigation — bleibt.
- **Batch-Rename:** `BatchRenameDialog` — bleibt.
- **macOS Full Disk Access Dialog:** `_macos_show_fda_dialog()` — bleibt.

---

## 7. Daten & Persistenz

Alle Einstellungen via `QSettings("fily", "fily")`:

| Schlüssel | Typ | Inhalt |
|-----------|-----|--------|
| `geometry` | bytes | Fenstergröße/-position |
| `splitter/main` | bytes | Favoriten-Splitter |
| `splitter/pane` | bytes | Dual-Pane-Splitter |
| `preview/visible` | bool | Drawer offen/zu |
| `preview/width` | int | Drawer-Breite in px |
| `columns/widths` | str | JSON-Array [w0,w1,w2,w3] |
| `columns/sort_col` | int | Sortier-Spalte (0-3) |
| `columns/sort_order` | int | Qt.SortOrder int |
| `view/mode` | str | `"list"` oder `"icon"` |
| `tabs/last_paths` | str | JSON-Array letzter Pfade je Tab |
| `favorites` | — | `~/.config/fily/favorites.json` |

---

## 8. PyInstaller onefile — Kompatibilität

- `_asset_path(rel)` in `config.py`: `sys._MEIPASS / rel` wenn eingefroren, sonst `__file__/../rel`.
- Alle `import`-Anweisungen in Untermodulen sind **relative Imports** (`from .config import ...`).
- `main.py` als Einstiegspunkt mit absolutem `import fily.mainwindow` o.ä. — oder flache Struktur ohne Package (alle Dateien auf gleicher Ebene → relative Imports mit `from config import ...`).
- **Entscheidung: flache Struktur** (kein `fily/`-Package-Ordner) — einfacher für PyInstaller, keine `__init__.py` nötig, Imports lauten `from config import ...`.
- `fily_app.spec` wird angepasst: `Analysis(['main.py'], ...)`, `hiddenimports` für PySide6-Plugins.

---

## 9. Abhängigkeiten

```
PySide6>=6.7
pyinstaller>=6.0
send2trash>=1.8
pyobjc-framework-Cocoa>=10.0; sys_platform == "darwin"
```

---

## 10. Nicht im Scope

- Cloud-Integration (iCloud, Dropbox, etc.)
- Netzlaufwerke / SMB-Browser
- Datei-Tagging / Spotlight-ähnliche Metadatensuche
- Plugin-System
- Symlink erstellen (nur anzeigen via Icon-Overlay, kein Erstellen)
