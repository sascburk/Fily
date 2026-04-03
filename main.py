#!/usr/bin/env python3
"""
Fily — Ein plattformübergreifender Dateiexplorer
Gebaut mit Python und PySide6 | Läuft auf macOS, Linux, Windows
"""

import sys
import os
import json
import shutil
import subprocess
from pathlib import Path

from send2trash import send2trash as _send2trash

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTreeView, QListView, QLabel, QLineEdit, QToolButton,
    QFrame, QMenu, QMessageBox, QInputDialog, QAbstractItemView,
    QHeaderView, QFileDialog, QSizePolicy, QPushButton,
    QFileSystemModel, QFileIconProvider,
    QTabWidget, QTabBar, QProgressDialog, QDialog, QDialogButtonBox,
    QTableWidget, QTableWidgetItem,
)
from PySide6.QtCore import (
    Qt, QObject, QModelIndex, QAbstractListModel, Signal, QTimer, QSettings,
    QMimeData, QUrl, QDir, QFileInfo, QSize, QThread, QEvent,
    QItemSelectionModel,
)
from PySide6.QtGui import (
    QKeySequence, QShortcut,
    QDesktopServices, QIcon, QColor, QPalette, QAction, QFont,
    QPainter, QLinearGradient, QBrush, QPen,
)

from config import (
    APP_NAME, ORG_NAME, VERSION, BUYMEACOFFEE_URL, GITHUB_URL,
    CONFIG_DIR, FAV_FILE, DEFAULT_FAVORITES,
    SK_GEOMETRY, SK_SPLITTER_MAIN, SK_SPLITTER_PANE,
    SK_PREVIEW_VISIBLE, SK_PREVIEW_WIDTH,
    SK_COL_WIDTHS, SK_COL_SORT_COL, SK_COL_SORT_ORDER,
    SK_VIEW_MODE, SK_LAST_PATH, SK_SHOW_HIDDEN, SK_FDA_HINT,
    asset_path,
)
from workers import UndoStack, CopyWorker
from models import FavoritesModel, ExplorerModel
from treeview import ExplorerTreeView
from dialogs import BatchRenameDialog, ShortcutsDialog, AboutDialog, _CtrlTabFilter
from favorites import FavoritesPanel
from addressbar import AddressBar
from fileops import build_ops, safe_trash, reveal_in_filemanager, get_clipboard_paths
from browser import FileBrowser


# ──────────────────────────────────────────────────────────────────────────────
# Tab-Bar mit Tear-Off (Tab aus Fenster ziehen → neues Fenster)
# ──────────────────────────────────────────────────────────────────────────────
class TearOffTabBar(QTabBar):
    """QTabBar, der bei einem Drag außerhalb des Fensters ein Signal auslöst."""

    tab_detached = Signal(int, object)   # tab-index, QPoint (global)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_pos = None
        self._press_idx = -1

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos = e.position().toPoint()
            self._press_idx = self.tabAt(self._press_pos)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._press_idx >= 0:
            release_global = self.mapToGlobal(e.position().toPoint())
            tab_widget = self.parent()
            if (
                isinstance(tab_widget, QTabWidget)
                and tab_widget.count() > 1
                and not self.window().frameGeometry().contains(release_global)
            ):
                self.tab_detached.emit(self._press_idx, release_global)
                self._press_idx = -1
                self._press_pos = None
                return
        self._press_idx = -1
        self._press_pos = None
        super().mouseReleaseEvent(e)


# ──────────────────────────────────────────────────────────────────────────────
# Hauptfenster
# ──────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, _initial_browser=None):
        super().__init__()
        self._initial_browser = _initial_browser
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(700, 440)

        s = QSettings(ORG_NAME, "MainWindow")
        geo = s.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1100, 680)

        self._build_ui()
        self._build_menu()
        self._install_window_shortcuts()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        center = QWidget()
        self.setCentralWidget(center)
        layout = QHBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)

        self.fav_panel = FavoritesPanel()

        # ── Tab-Widget ────────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        tear_bar = TearOffTabBar()
        tear_bar.tab_detached.connect(self._detach_tab)
        self.tabs.setTabBar(tear_bar)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)   # macOS-nativer Tab-Stil
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)

        btn_new_tab = QToolButton()
        btn_new_tab.setText(" + ")
        btn_new_tab.setToolTip("Neuer Tab  (Ctrl+T)")
        btn_new_tab.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_new_tab.clicked.connect(self._new_tab)
        self.tabs.setCornerWidget(btn_new_tab, Qt.Corner.TopRightCorner)

        # Ersten Tab öffnen (ggf. mit übergebenem Browser beim Tear-Off)
        s = QSettings(ORG_NAME, "MainWindow")
        if self._initial_browser is not None:
            self._add_existing_tab(self._initial_browser)
        else:
            start_path = s.value("last_path", str(Path.home()))
            self._add_tab(start_path)
        self.fav_panel.navigate.connect(self._fav_navigate)

        self.splitter.addWidget(self.fav_panel)
        self.splitter.addWidget(self.tabs)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([190, 900])

        sp = s.value("splitter")
        if sp:
            self.splitter.restoreState(sp)

        layout.addWidget(self.splitter)

    def _add_tab(self, path: str | None = None) -> "FileBrowser":
        """Fügt einen neuen Tab hinzu und gibt den Browser zurück."""
        browser = FileBrowser(path)
        browser.path_changed.connect(self._path_changed)
        browser.request_add_fav.connect(self.fav_panel.add_current)
        name = Path(path).name if path else "Home"
        idx = self.tabs.addTab(browser, name or "/")
        self.tabs.setCurrentIndex(idx)
        return browser

    def _add_existing_tab(self, browser: "FileBrowser"):
        """Nimmt einen bestehenden Browser-Widget auf (z. B. nach Tear-Off)."""
        browser.path_changed.connect(self._path_changed)
        browser.request_add_fav.connect(self.fav_panel.add_current)
        name = Path(browser.current_path).name or "/"
        idx = self.tabs.addTab(browser, name)
        self.tabs.setCurrentIndex(idx)

    def _detach_tab(self, idx: int, global_pos):
        """Löst einen Tab aus und öffnet ihn in einem neuen Fenster."""
        if self.tabs.count() <= 1:
            return
        browser = self.tabs.widget(idx)
        if not isinstance(browser, FileBrowser):
            return
        # Signale vom alten Fenster trennen
        try:
            browser.path_changed.disconnect(self._path_changed)
            browser.request_add_fav.disconnect(self.fav_panel.add_current)
        except RuntimeError:
            pass
        self.tabs.removeTab(idx)
        new_win = MainWindow(_initial_browser=browser)
        new_win.resize(self.size())
        new_win.show()
        new_win.move(global_pos.x() - new_win.width() // 2,
                     global_pos.y() - 30)

    def _new_tab(self):
        cur = self.current_browser
        self._add_tab(cur.current_path if cur else str(Path.home()))

    def _close_tab(self, idx: int):
        if self.tabs.count() > 1:
            self.tabs.removeTab(idx)

    @property
    def current_browser(self) -> "FileBrowser | None":
        w = self.tabs.currentWidget()
        return w if isinstance(w, FileBrowser) else None

    def focusNextPrevChild(self, next_: bool) -> bool:
        """4-Stop Tab-Reihenfolge: Favoriten → Adresse → Suche → Inhalt → zurück."""
        cur = self.current_browser
        if cur is None:
            return super().focusNextPrevChild(next_)
        stops = [self.fav_panel.view, cur.addr, cur.search, cur.tree]
        focused = QApplication.focusWidget()
        try:
            idx = stops.index(focused)
        except ValueError:
            return super().focusNextPrevChild(next_)
        next_idx = (idx + (1 if next_ else -1)) % len(stops)
        stops[next_idx].setFocus(Qt.FocusReason.TabFocusReason)
        return True

    def _fav_navigate(self, path: str):
        cur = self.current_browser
        if cur:
            cur.navigate(path)
            cur.focus_and_select_first()

    def _tab_changed(self, idx: int):
        browser = self.tabs.widget(idx)
        if isinstance(browser, FileBrowser):
            self._path_changed(browser.current_path)

    # ── Fensterkürzel (Tab-Navigation) ────────────────────────────────────────
    def _install_window_shortcuts(self):
        # Ctrl+T / Ctrl+W werden nur über Menü-Aktionen definiert (kein QShortcut — sonst ambiguous)
        win_pairs = [
            # Fokus-Shortcuts (wirken auch wenn Favoritenleiste den Fokus hat)
            (Qt.Modifier.CTRL | Qt.Key.Key_F,
             lambda: self.current_browser and self.current_browser._focus_search()),
            (Qt.Modifier.CTRL | Qt.Key.Key_L,
             lambda: self.current_browser and self.current_browser._focus_addr()),
            (Qt.Key.Key_F4,
             lambda: self.current_browser and self.current_browser._focus_addr()),
        ]

        if sys.platform == "darwin":
            # macOS: Cmd+Shift+←/→ via App-Event-Filter
            # (System schluckt Ctrl+Tab auf Systemebene)
            self._tab_filter = _CtrlTabFilter(self)
            QApplication.instance().installEventFilter(self._tab_filter)
        else:
            # Windows / Linux: Ctrl+Tab und Ctrl+Shift+Tab als WindowShortcut
            win_pairs += [
                (QKeySequence("Ctrl+Tab"),       self._next_tab),
                (QKeySequence("Ctrl+Shift+Tab"), self._prev_tab),
            ]

        for combo, slot in win_pairs:
            sc = QShortcut(QKeySequence(combo) if isinstance(combo, int) else combo, self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)

    def _next_tab(self):
        n = self.tabs.count()
        if n > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % n)

    def _prev_tab(self):
        n = self.tabs.count()
        if n > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % n)

    def _build_menu(self):
        mb = self.menuBar()

        # ── Datei ─────────────────────────────────────────────────────────────
        m = mb.addMenu("Datei")
        self._a(m, "Neuer Ordner",  "Ctrl+N",  lambda: self.current_browser and self.current_browser._new_folder())
        self._a(m, "Neuer Tab",     "Ctrl+T",  self._new_tab)
        self._a(m, "Tab schließen", "Ctrl+W",  lambda: self._close_tab(self.tabs.currentIndex()))
        m.addSeparator()
        self._a(m, "Aktuellen Ordner zu Favoriten",
                callback=lambda: self.current_browser and self.fav_panel.add_current(
                    self.current_browser.current_path))
        m.addSeparator()
        self._a(m, "Beenden", "Ctrl+Q", self.close)

        # ── Bearbeiten ────────────────────────────────────────────────────────
        m = mb.addMenu("Bearbeiten")
        self._a(m, "Ausschneiden",         "Ctrl+X",  lambda: self.current_browser and self.current_browser._cut())
        self._a(m, "Kopieren",             "Ctrl+C",  lambda: self.current_browser and self.current_browser._copy())
        self._a(m, "Einfügen",             "Ctrl+V",  lambda: self.current_browser and self.current_browser._paste())
        m.addSeparator()
        self._a(m, "Alle auswählen",       "Ctrl+A",  lambda: self.current_browser and self.current_browser.tree.selectAll())
        m.addSeparator()
        self._a(m, "Umbenennen",           "F2",      lambda: self.current_browser and self.current_browser._rename())
        self._a(m, "Mehrfach umbenennen",  "",        lambda: self.current_browser and self.current_browser._batch_rename())
        trash_sc = "Meta+Backspace" if sys.platform == "darwin" else "Delete"
        self._a(m, "In Papierkorb", trash_sc, lambda: self.current_browser and self.current_browser._delete())
        m.addSeparator()
        self._a(m, "Rückgängig",           "Ctrl+Z",  lambda: self.current_browser and self.current_browser._undo())

        # ── Ansicht ───────────────────────────────────────────────────────────
        m = mb.addMenu("Ansicht")
        self._a(m, "Aktualisieren", "F5", lambda: self.current_browser and self.current_browser.refresh())

        # ── Hilfe ─────────────────────────────────────────────────────────────
        m = mb.addMenu("Hilfe")
        self._a(m, f"Über {APP_NAME} …", callback=self._open_about)
        self._a(m, "Tastaturkürzel …",   callback=lambda: ShortcutsDialog(self).exec())
        m.addSeparator()
        self._a(m, "☕  Buy me a coffee", callback=lambda: QDesktopServices.openUrl(QUrl(BUYMEACOFFEE_URL)))
        self._a(m, "GitHub", callback=lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))

        # ── Gehe zu ───────────────────────────────────────────────────────────
        m = mb.addMenu("Gehe zu")
        self._a(m, "Zurück",       "Alt+Left",  lambda: self.current_browser and self.current_browser.go_back())
        self._a(m, "Vor",          "Alt+Right", lambda: self.current_browser and self.current_browser.go_forward())
        self._a(m, "Übergeordnet", "Alt+Up",    lambda: self.current_browser and self.current_browser.go_up())

    @staticmethod
    def _a(menu: QMenu, text: str, shortcut: str | None = None,
           callback=None) -> QAction:
        action = menu.addAction(text)
        if shortcut:
            action.setShortcut(shortcut)
        if callback:
            action.triggered.connect(callback)
        return action

    def _open_about(self):
        AboutDialog(self).exec()

    # ── Slots ─────────────────────────────────────────────────────────────────
    def _path_changed(self, path: str):
        # Nur reagieren, wenn der Signal vom aktiven Tab kommt
        if self.sender() is not self.current_browser:
            return
        name = Path(path).name or path
        self.setWindowTitle(f"{name}  —  {APP_NAME}")
        self.fav_panel.highlight_path(path)
        # Tab-Titel aktualisieren
        idx = self.tabs.currentIndex()
        if idx >= 0:
            self.tabs.setTabText(idx, name or "/")

    def closeEvent(self, event):
        s = QSettings(ORG_NAME, "MainWindow")
        s.setValue("geometry",  self.saveGeometry())
        s.setValue("splitter",  self.splitter.saveState())
        cur = self.current_browser
        if cur:
            s.setValue("last_path", cur.current_path)
        super().closeEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# Einstiegspunkt
# ──────────────────────────────────────────────────────────────────────────────
def _linux_is_dark() -> bool:
    """Erkennt Dark Mode auf Linux: gsettings → GTK-Config-Dateien."""
    # Methode 1: GNOME gsettings
    try:
        out = subprocess.check_output(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip().strip("'\"")
        if "dark" in out.lower():
            return True
    except Exception:
        pass

    # Methode 2: dconf-Datenbank direkt lesen (kein D-Bus nötig).
    # gsettings/dconf speichern den Wert als lesbaren String in der Binärdatei.
    try:
        data = (Path.home() / ".config" / "dconf" / "user").read_bytes()
        if b"prefer-dark" in data:
            return True
    except Exception:
        pass

    # Methode 3: GTK-Config-Datei (~/.config/gtk-4.0 oder gtk-3.0)
    for conf in [
        Path.home() / ".config" / "gtk-4.0" / "settings.ini",
        Path.home() / ".config" / "gtk-3.0" / "settings.ini",
    ]:
        try:
            text = conf.read_text(encoding="utf-8").lower()
            if "gtk-application-prefer-dark-theme=1" in text or \
               "gtk-application-prefer-dark-theme=true" in text or \
               "color-scheme=prefer-dark" in text:
                return True
        except Exception:
            pass

    return False


def _apply_dark_palette(app: QApplication) -> None:
    """Apply a Fusion-based dark palette to the QApplication."""
    from PySide6.QtGui import QColor, QPalette
    app.setStyle("Fusion")
    p = QPalette()
    dark   = QColor(45, 45, 45)
    mid    = QColor(65, 65, 65)
    light  = QColor(90, 90, 90)
    text   = QColor(220, 220, 220)
    hi     = QColor(42, 130, 218)
    p.setColor(QPalette.ColorRole.Window,          dark)
    p.setColor(QPalette.ColorRole.WindowText,      text)
    p.setColor(QPalette.ColorRole.Base,            QColor(30, 30, 30))
    p.setColor(QPalette.ColorRole.AlternateBase,   dark)
    p.setColor(QPalette.ColorRole.ToolTipBase,     dark)
    p.setColor(QPalette.ColorRole.ToolTipText,     text)
    p.setColor(QPalette.ColorRole.Text,            text)
    p.setColor(QPalette.ColorRole.Button,          mid)
    p.setColor(QPalette.ColorRole.ButtonText,      text)
    p.setColor(QPalette.ColorRole.Mid,             mid)
    p.setColor(QPalette.ColorRole.Midlight,        QColor(75, 75, 75))
    p.setColor(QPalette.ColorRole.Dark,            QColor(35, 35, 35))
    p.setColor(QPalette.ColorRole.Shadow,          QColor(20, 20, 20))
    p.setColor(QPalette.ColorRole.BrightText,      QColor(255, 50, 50))
    p.setColor(QPalette.ColorRole.Link,            hi)
    p.setColor(QPalette.ColorRole.Highlight,       hi)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, light)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, light)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,       light)
    app.setPalette(p)


def _macos_show_fda_dialog(parent=None) -> None:
    """Zeigt einmalig pro App-Start einen Dialog für Full Disk Access (macOS).

    Nutzt QSettings um zu vermerken, ob der Dialog in dieser Sitzung bereits
    angezeigt wurde — verhindert wiederholtes Erscheinen beim Navigieren.
    """
    s = QSettings(ORG_NAME, "Permissions")
    if s.value("fda_hint_shown", False, type=bool):
        return
    s.setValue("fda_hint_shown", True)

    dlg = QMessageBox(parent)
    dlg.setWindowTitle("Zugriff eingeschränkt")
    dlg.setIcon(QMessageBox.Icon.Warning)
    dlg.setText(
        "<b>Fily hat keinen Zugriff auf diesen Ordner.</b><br><br>"
        "macOS schränkt den Zugriff auf bestimmte Verzeichnisse ein "
        "(z. B. Desktop, Dokumente, Downloads, externe Laufwerke).<br><br>"
        "Erlaube den Vollzugriff auf Dateien unter:<br>"
        "<i>Systemeinstellungen → Datenschutz &amp; Sicherheit → "
        "Vollzugriff auf Dateien</i>"
    )
    btn_settings = dlg.addButton("Zu Einstellungen", QMessageBox.ButtonRole.ActionRole)
    dlg.addButton("Schließen", QMessageBox.ButtonRole.RejectRole)
    dlg.exec()
    if dlg.clickedButton() == btn_settings:
        subprocess.run([
            "open",
            "x-apple.systempreferences:"
            "com.apple.preference.security?Privacy_AllFiles",
        ])


def main():
    # Linux: Umgebung vor QApplication vorbereiten.
    _linux_dark = False
    if sys.platform.startswith("linux"):
        # Ubuntu: disable global AppMenu integration — prevents menu bar from
        # disappearing immediately after click (BAMF/Unity proxy hijacks Qt menus).
        os.environ["UBUNTU_MENUPROXY"] = "0"

        # Unterdrücke harmlose GTK-Warnungen über nicht installierte Module
        # (canberra-gtk-module, pk-gtk-module) — diese sind optional und nicht
        # erforderlich für Fily. Erzwungene Überschreibung, da GTK_MODULES oft
        # von der Desktop-Session geerbt wird.
        os.environ["GTK_MODULES"] = ""

        # Unterdrücke Qt-D-Bus-Portal-Warnung "Could not register app ID"
        # — tritt auf wenn die App via Symlink gestartet wird und die D-Bus-
        # Verbindung bereits eine App-ID hat; die App funktioniert trotzdem.
        _existing_rules = os.environ.get("QT_LOGGING_RULES", "")
        _portal_rule = "qt.qpa.services=false"
        if _portal_rule not in _existing_rules:
            os.environ["QT_LOGGING_RULES"] = (
                f"{_existing_rules};{_portal_rule}" if _existing_rules else _portal_rule
            )

        # Dark-Mode-Erkennung VOR QApplication, damit QT_STYLE_OVERRIDE greift
        # bevor Qt das Plattform-Theme lädt (Fedora/GNOME überschreibt sonst
        # eine nachträglich gesetzte Palette).
        _linux_dark = _linux_is_dark()
        if _linux_dark:
            # Plattform-Theme entfernen — GNOME/GTK-Theme würde unsere
            # Fusion-Palette nach dem Start wieder überschreiben.
            os.environ.pop("QT_QPA_PLATFORMTHEME", None)
            os.environ["QT_STYLE_OVERRIDE"] = "Fusion"

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)

    # FDA-Hinweis-Flag zurücksetzen, damit er pro Sitzung einmal erscheinen kann.
    if sys.platform == "darwin":
        QSettings(ORG_NAME, "Permissions").setValue("fda_hint_shown", False)

    # App-Icon setzen (Taskleiste / Dock / Alt+Tab)
    if sys.platform == "win32":
        # Windows: .ico verwenden; AppUserModelID setzen damit Taskleiste
        # das Icon der .exe zuordnet (statt Python-Interpreter-Icon).
        try:
            import ctypes
            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "com.fily.app"
                )
        except Exception:
            pass
        icon_path = asset_path("assets", "icons", "windows", "icon.ico")
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
    elif sys.platform.startswith("linux"):
        icon_path = asset_path("assets", "icons", "linux", "256x256.png")
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
        # GNOME verknüpft die laufende App mit dem .desktop-Eintrag über
        # diesen Namen — ohne dies zeigt die Taskleiste das Zahnrad-Icon.
        app.setDesktopFileName("fily")

    # Linux: Fusion dark palette anwenden (Erkennung bereits oben erfolgt).
    if _linux_dark:
        _apply_dark_palette(app)

    if sys.platform == "darwin":
        app.setApplicationDisplayName(APP_NAME)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
