"""
mainwindow.py — TearOffTabBar und MainWindow.

MainWindow verwaltet: Splitter (FavoritesPanel | QTabWidget), Menüleiste,
Fenster-Shortcuts, Persistenz von Geometrie und letztem Pfad.
"""
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter, QTabWidget, QTabBar,
    QToolButton, QMenu, QApplication,
)
from PySide6.QtCore import Qt, QSettings, Signal, QPoint, QUrl, QEvent
from PySide6.QtGui import QAction, QKeySequence, QDesktopServices, QShortcut

from config import APP_NAME, ORG_NAME, BUYMEACOFFEE_URL, GITHUB_URL, SK_GEOMETRY, SK_SPLITTER_MAIN, SK_LAST_PATH, SK_PREVIEW_VISIBLE, SK_PREVIEW_WIDTH
from browser import FileBrowser
from favorites import FavoritesPanel
from dialogs import ShortcutsDialog, AboutDialog, _CtrlTabFilter
from preview import PreviewDrawer


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

        # Vorschau-Drawer (rechts, per F9 ein-/ausblendbar)
        self.preview = PreviewDrawer()
        self.splitter.addWidget(self.preview)
        self.splitter.setStretchFactor(0, 0)   # FavoritesPanel: fest
        self.splitter.setStretchFactor(1, 1)   # Tabs: flexibel
        self.splitter.setStretchFactor(2, 0)   # Preview: fest
        self.splitter.setSizes([190, 900, 0])

        # Vorschau-Zustand wiederherstellen
        preview_visible = s.value(SK_PREVIEW_VISIBLE, False, type=bool)
        self.preview.setVisible(preview_visible)

        sp = s.value(SK_SPLITTER_MAIN)
        if sp:
            self.splitter.restoreState(sp)

        layout.addWidget(self.splitter)

    def _add_tab(self, path: str | None = None) -> "FileBrowser":
        """Fügt einen neuen Tab hinzu und gibt den Browser zurück."""
        browser = FileBrowser(path)
        browser.path_changed.connect(self._path_changed)
        browser.selection_changed.connect(self._on_selection_changed)
        browser.request_add_fav.connect(self.fav_panel.add_current)
        name = Path(path).name if path else "Home"
        idx = self.tabs.addTab(browser, name or "/")
        self.tabs.setCurrentIndex(idx)
        return browser

    def _add_existing_tab(self, browser: "FileBrowser"):
        """Nimmt einen bestehenden Browser-Widget auf (z. B. nach Tear-Off)."""
        browser.path_changed.connect(self._path_changed)
        browser.selection_changed.connect(self._on_selection_changed)
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
            (Qt.Key.Key_F9,    self._toggle_preview),
            (Qt.Key.Key_Space, self._toggle_preview),
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

    def _toggle_preview(self):
        """Schaltet den Vorschau-Drawer ein/aus (F9 / Space)."""
        visible = not self.preview.isVisible()
        self.preview.setVisible(visible)
        s = QSettings(ORG_NAME, "MainWindow")
        s.setValue(SK_PREVIEW_VISIBLE, visible)

    def _on_selection_changed(self, path: str):
        """Aktualisiert die Vorschau wenn sich die Auswahl ändert."""
        if self.preview.isVisible():
            if path:
                self.preview.show_path(path)
            else:
                self.preview.clear_preview()

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
        s.setValue("geometry",      self.saveGeometry())
        s.setValue(SK_SPLITTER_MAIN, self.splitter.saveState())
        cur = self.current_browser
        if cur:
            s.setValue("last_path", cur.current_path)
        super().closeEvent(event)
