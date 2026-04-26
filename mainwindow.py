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
from PySide6.QtCore import Qt, QSettings, Signal, QPoint, QUrl, QTimer, QRectF, QEvent
from PySide6.QtGui import QAction, QKeySequence, QDesktopServices, QShortcut, QRegion, QPainterPath

from config import (
    APP_NAME, ORG_NAME, BUYMEACOFFEE_URL, GITHUB_URL,
    SK_GEOMETRY, SK_SPLITTER_MAIN, SK_SPLITTER_PANE,
    SK_LAST_PATH, SK_PREVIEW_VISIBLE,
)
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
    tab_dropped_to_other = Signal(int, object, object)  # tab-index, target QTabBar, drop global QPoint
    tab_drag_hover_target = Signal(object, object)  # target QTabBar | None, global QPoint | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_pos = None
        self._press_idx = -1
        self._hover_target = None

    @staticmethod
    def _tab_bar_at_global_pos(global_pos):
        target = QApplication.widgetAt(global_pos)
        while target is not None and not isinstance(target, QTabBar):
            target = target.parentWidget()
        return target if isinstance(target, QTabBar) else None

    def _set_hover_target(self, target):
        if target is self:
            target = None
        if target is self._hover_target:
            return
        self._hover_target = target
        # Position wird im Move-Event separat emittiert.

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos = e.position().toPoint()
            self._press_idx = self.tabAt(self._press_pos)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (
            self._press_idx >= 0
            and (e.buttons() & Qt.MouseButton.LeftButton)
        ):
            global_pos = self.mapToGlobal(e.position().toPoint())
            target = self._tab_bar_at_global_pos(global_pos)
            self._set_hover_target(target)
            self.tab_drag_hover_target.emit(self._hover_target, global_pos)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._press_idx >= 0:
            release_global = self.mapToGlobal(e.position().toPoint())
            tab_widget = self.parent()

            # Tab auf andere Tab-Leiste gezogen (links <-> rechts)
            target = self._tab_bar_at_global_pos(release_global)
            if (
                isinstance(tab_widget, QTabWidget)
                and isinstance(target, QTabBar)
                and target is not self
            ):
                self.tab_dropped_to_other.emit(self._press_idx, target, release_global)
                self._set_hover_target(None)
                self.tab_drag_hover_target.emit(None, None)
                self._press_idx = -1
                self._press_pos = None
                return

            if (
                isinstance(tab_widget, QTabWidget)
                and tab_widget.count() > 1
                and not self.window().frameGeometry().contains(release_global)
            ):
                self.tab_detached.emit(self._press_idx, release_global)
                self._set_hover_target(None)
                self.tab_drag_hover_target.emit(None, None)
                self._press_idx = -1
                self._press_pos = None
                return
        self._set_hover_target(None)
        self.tab_drag_hover_target.emit(None, None)
        self._press_idx = -1
        self._press_pos = None
        super().mouseReleaseEvent(e)


# ──────────────────────────────────────────────────────────────────────────────
# Hauptfenster
# ──────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, _initial_browser=None):
        super().__init__()
        self._corner_radius = 12
        self._custom_chrome = (sys.platform == "darwin")
        if self._custom_chrome:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._initial_browser = _initial_browser
        self._win_drag_active = False
        self._win_drag_offset = QPoint(0, 0)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(700, 440)

        self._build_ui()
        self._build_menu()
        self._install_window_shortcuts()
        if self._custom_chrome:
            QTimer.singleShot(0, self._update_window_mask)

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        center = QWidget()
        center.setObjectName("windowFrame")
        if self._custom_chrome:
            center.setStyleSheet(
                "QWidget#windowFrame {"
                " background: palette(window);"
                " border: 1px solid palette(mid);"
                " border-radius: 12px;"
                "}"
            )
        self.setCentralWidget(center)
        main_layout = QHBoxLayout(center)
        if self._custom_chrome:
            main_layout.setContentsMargins(1, 1, 1, 1)
        else:
            main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Haupt-Splitter: Favoriten | Browser-Bereich | Vorschau ───────────────
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)

        self.fav_panel = FavoritesPanel()
        self.fav_panel.set_window_controls_visible(self._custom_chrome)
        if self._custom_chrome:
            self.fav_panel.window_close.connect(self.close)
            self.fav_panel.window_minimize.connect(self.showMinimized)
            self.fav_panel.window_maximize_toggle.connect(self._toggle_maximize_restore)
            self.fav_panel.window_drag_start.connect(self._window_drag_start)
            self.fav_panel.window_drag_move.connect(self._window_drag_move)
            self.fav_panel.window_drag_end.connect(self._window_drag_end)

        # ── Browser-Bereich: linke + rechte Tab-Gruppe (Dual-Pane) ───────────────
        self._browser_container = QWidget()
        browser_layout = QHBoxLayout(self._browser_container)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.setSpacing(0)

        # Splitter zwischen linker und rechter Tab-Gruppe
        self._pane_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._pane_splitter.setHandleWidth(2)

        # Linke Tab-Gruppe (immer sichtbar)
        self.tabs = self._make_tab_widget()
        self._pane_splitter.addWidget(self.tabs)

        # Rechte Tab-Gruppe (nur bei Dual-Pane, F8)
        self.tabs_right = self._make_tab_widget()
        self.tabs_right.setVisible(False)
        self._pane_splitter.addWidget(self.tabs_right)

        browser_layout.addWidget(self._pane_splitter)

        # Vorschau-Drawer (wiederverwendet aus Task 16)
        self.preview = PreviewDrawer()

        self.splitter.addWidget(self.fav_panel)
        self.splitter.addWidget(self._browser_container)
        self.splitter.addWidget(self.preview)
        self.splitter.setStretchFactor(0, 0)   # FavoritesPanel: fest
        self.splitter.setStretchFactor(1, 1)   # Browser-Bereich: flexibel
        self.splitter.setStretchFactor(2, 0)   # Preview: fest
        self.splitter.setCollapsible(0, False)  # Favoritenleiste kann nicht ausgeblendet werden

        # Gespeicherten Zustand wiederherstellen
        s = QSettings(ORG_NAME, "MainWindow")
        geo = s.value(SK_GEOMETRY)
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1200, 700)

        splitter_state = s.value(SK_SPLITTER_MAIN)
        if splitter_state:
            self.splitter.restoreState(splitter_state)
        else:
            self.splitter.setSizes([190, 900, 0])

        pane_state = s.value(SK_SPLITTER_PANE)
        if pane_state:
            self._pane_splitter.restoreState(pane_state)

        preview_visible = s.value(SK_PREVIEW_VISIBLE, False, type=bool)
        self.preview.setVisible(preview_visible)

        # Ersten Tab öffnen
        if self._initial_browser is not None:
            self._add_existing_tab(self._initial_browser, self.tabs)
        else:
            start_path = s.value(SK_LAST_PATH, str(Path.home()))
            self._add_tab(start_path, self.tabs)
        self._update_tab_bar_visibility()

        self.fav_panel.navigate.connect(self._fav_navigate)

        main_layout.addWidget(self.splitter)

    def _toggle_maximize_restore(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        if self._custom_chrome:
            QTimer.singleShot(0, self._update_window_mask)

    def _window_drag_start(self, global_pos):
        if not self._custom_chrome:
            return
        if self.isMaximized():
            self.showNormal()
            QTimer.singleShot(0, self._update_window_mask)
        self._win_drag_active = True
        self._win_drag_offset = global_pos - self.frameGeometry().topLeft()

    def _window_drag_move(self, global_pos):
        if not self._custom_chrome or not self._win_drag_active:
            return
        self.move(global_pos - self._win_drag_offset)

    def _window_drag_end(self):
        self._win_drag_active = False

    def _update_window_mask(self):
        if not self._custom_chrome:
            return
        if self.isMaximized():
            self.clearMask()
            return
        rr = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rr, self._corner_radius, self._corner_radius)
        region = QRegion(path.toFillPolygon().toPolygon())
        self.setMask(region)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._custom_chrome:
            self._update_window_mask()

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform.startswith("linux"):
            self.menuBar().setNativeMenuBar(False)

    def changeEvent(self, event):
        super().changeEvent(event)
        if (
            sys.platform.startswith("linux")
            and event.type() == QEvent.Type.WindowActivate
        ):
            self.menuBar().setNativeMenuBar(False)

    def _make_tab_widget(self) -> QTabWidget:
        """Erstellt ein konfiguriertes QTabWidget mit TearOffTabBar."""
        tw = QTabWidget()
        tear_bar = TearOffTabBar()
        tear_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tear_bar.setExpanding(False)   # Tabs linksbündig, nicht gestreckt
        tear_bar.tab_detached.connect(self._detach_tab)
        tear_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tear_bar.customContextMenuRequested.connect(
            lambda pos, _tw=tw: self._tab_bar_ctx_menu(pos, _tw)
        )
        tear_bar.tab_dropped_to_other.connect(
            lambda idx, target_bar, drop_pos, _tw=tw: self._handle_cross_pane_tab_drop(_tw, idx, target_bar, drop_pos)
        )
        tear_bar.tab_drag_hover_target.connect(self._update_tab_drop_indicator)
        tw.setTabBar(tear_bar)
        tw.setTabsClosable(False)  # Eigene Buttons via _add_close_btn
        tw.setTabBarAutoHide(True)  # Im Split-Modus per _update_tab_bar_visibility überschrieben
        tw.setMovable(True)
        tw.setDocumentMode(True)
        tw.currentChanged.connect(lambda idx, t=tw: self._tab_changed(idx, t))
        return tw

    def _add_close_btn(self, tw: QTabWidget, idx: int, browser: "FileBrowser"):
        """Setzt einen Schließen-Button rechts auf den Tab."""
        btn = QToolButton()
        btn.setText("✕")
        btn.setFixedSize(16, 16)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setAutoRaise(True)
        btn.setToolTip("Tab schließen")
        btn.clicked.connect(lambda _, w=browser, t=tw: self._close_tab(t.indexOf(w), t))
        tw.tabBar().setTabButton(idx, QTabBar.ButtonPosition.RightSide, btn)

    def _add_tab(self, path: str | None = None, tab_widget: QTabWidget | None = None) -> "FileBrowser":
        """Fügt einen neuen Tab hinzu und gibt den Browser zurück."""
        tw = tab_widget or self.tabs
        browser = FileBrowser(path)
        browser.set_window_drag_enabled(self._custom_chrome)
        browser.path_changed.connect(self._path_changed)
        browser.request_add_fav.connect(self.fav_panel.add_current)
        browser.request_new_tab.connect(lambda t=tw: self._new_tab(t))
        browser.request_open_path_in_new_tab.connect(lambda p, t=tw: self._add_tab(p, t))
        if self._custom_chrome:
            browser.request_window_drag_start.connect(self._window_drag_start)
            browser.request_window_drag_move.connect(self._window_drag_move)
            browser.request_window_drag_end.connect(self._window_drag_end)
        browser.selection_changed.connect(self._on_selection_changed)
        name = Path(path).name if path else "Home"
        idx = tw.addTab(browser, name or "/")
        self._add_close_btn(tw, idx, browser)
        tw.setCurrentIndex(idx)
        self._update_tab_bar_visibility()
        return browser

    def _add_existing_tab(self, browser: "FileBrowser", tab_widget: QTabWidget | None = None):
        """Nimmt einen bestehenden Browser-Widget auf (z. B. nach Tear-Off)."""
        tw = tab_widget or self.tabs
        browser.set_window_drag_enabled(self._custom_chrome)
        browser.path_changed.connect(self._path_changed)
        browser.request_add_fav.connect(self.fav_panel.add_current)
        browser.request_new_tab.connect(lambda t=tw: self._new_tab(t))
        browser.request_open_path_in_new_tab.connect(lambda p, t=tw: self._add_tab(p, t))
        if self._custom_chrome:
            browser.request_window_drag_start.connect(self._window_drag_start)
            browser.request_window_drag_move.connect(self._window_drag_move)
            browser.request_window_drag_end.connect(self._window_drag_end)
        browser.selection_changed.connect(self._on_selection_changed)
        name = Path(browser.current_path).name or "/"
        idx = tw.addTab(browser, name)
        self._add_close_btn(tw, idx, browser)
        tw.setCurrentIndex(idx)
        self._update_tab_bar_visibility()

    def _detach_tab(self, idx: int, global_pos):
        """Löst einen Tab aus und öffnet ihn in einem neuen Fenster."""
        # Finde das TabWidget, das diesen Tab enthält
        sender_bar = self.sender()
        tw = self.tabs
        if hasattr(self, 'tabs_right') and sender_bar is self.tabs_right.tabBar():
            tw = self.tabs_right
        if tw.count() <= 1:
            return
        browser = tw.widget(idx)
        if not isinstance(browser, FileBrowser):
            return
        try:
            browser.path_changed.disconnect(self._path_changed)
            browser.request_add_fav.disconnect(self.fav_panel.add_current)
            browser.request_new_tab.disconnect()
            browser.request_open_path_in_new_tab.disconnect()
            if self._custom_chrome:
                browser.request_window_drag_start.disconnect(self._window_drag_start)
                browser.request_window_drag_move.disconnect(self._window_drag_move)
                browser.request_window_drag_end.disconnect(self._window_drag_end)
            browser.selection_changed.disconnect(self._on_selection_changed)
        except (RuntimeError, TypeError):
            pass
        tw.removeTab(idx)
        self._update_tab_bar_visibility()
        new_win = MainWindow(_initial_browser=browser)
        new_win.resize(self.size())
        new_win.show()
        new_win.move(global_pos.x() - new_win.width() // 2, global_pos.y() - 30)

    def _new_tab(self, tab_widget: QTabWidget | None = None):
        tw = tab_widget or self.tabs
        cur = self._current_browser_in(tw)
        self._add_tab(cur.current_path if cur else str(Path.home()), tw)

    def _close_tab(self, idx: int, tab_widget: QTabWidget | None = None):
        tw = tab_widget or self.tabs
        if tw.count() > 1:
            tw.removeTab(idx)
            self._update_tab_bar_visibility()
        elif tw is self.tabs_right:
            # Letzter Tab im rechten Pane → Split-Modus beenden
            self.tabs_right.setVisible(False)
            self._update_tab_bar_visibility()
        elif tw is self.tabs and self.tabs_right.isVisible():
            # Letzter Tab im linken Pane während Split aktiv → Split beenden
            self.tabs_right.setVisible(False)
            self._update_tab_bar_visibility()

    def _tab_bar_ctx_menu(self, pos, tw: QTabWidget):
        """Kontextmenü auf der Tab-Leiste — nur im Split-Modus."""
        if not self.tabs_right.isVisible():
            return
        idx = tw.tabBar().tabAt(pos)
        if idx < 0:
            return
        target_is_right = tw is self.tabs
        direction = "rechte" if target_is_right else "linke"
        menu = QMenu(self)
        move_action = menu.addAction(f"In {direction} Pane verschieben")
        # Letzten Tab der linken Pane nicht verschieben (linke Pane darf nicht leer werden)
        if tw is self.tabs and tw.count() <= 1:
            move_action.setEnabled(False)
        if menu.exec(tw.tabBar().mapToGlobal(pos)) == move_action:
            self._move_tab_to_other_pane(tw, idx)

    def _move_tab_to_other_pane(self, source: QTabWidget, idx: int):
        """Verschiebt einen Tab von einer Pane in die andere."""
        target = self.tabs_right if source is self.tabs else self.tabs
        self._move_tab_between_panes(source, idx, target)

    def _move_tab_between_panes(
        self,
        source: QTabWidget,
        idx: int,
        target: QTabWidget,
        target_insert_idx: int | None = None,
        emphasize: bool = False,
    ):
        """Verschiebt einen Tab von source nach target."""
        if source is target:
            return
        if source is self.tabs and source.count() <= 1:
            # Linke Pane darf nie leer werden
            return
        browser = source.widget(idx)
        if not isinstance(browser, FileBrowser):
            return
        try:
            browser.path_changed.disconnect(self._path_changed)
            browser.request_add_fav.disconnect(self.fav_panel.add_current)
            browser.request_new_tab.disconnect()
            browser.request_open_path_in_new_tab.disconnect()
            if self._custom_chrome:
                browser.request_window_drag_start.disconnect(self._window_drag_start)
                browser.request_window_drag_move.disconnect(self._window_drag_move)
                browser.request_window_drag_end.disconnect(self._window_drag_end)
            browser.selection_changed.disconnect(self._on_selection_changed)
        except (RuntimeError, TypeError):
            pass
        source.removeTab(idx)
        inserted_idx = self._insert_existing_tab(browser, target, target_insert_idx)
        if emphasize:
            self._emphasize_moved_tab(target, inserted_idx)
        # Rechte Pane ist jetzt leer → Split-Modus beenden
        if source is self.tabs_right and source.count() == 0:
            self.tabs_right.setVisible(False)
        self._update_tab_bar_visibility()

    def _handle_cross_pane_tab_drop(self, source: QTabWidget, idx: int, target_bar: QTabBar, drop_pos):
        """Behandelt Maus-Drop eines Tabs auf die jeweils andere Pane."""
        target_tw: QTabWidget | None = None
        if target_bar is self.tabs.tabBar():
            target_tw = self.tabs
        elif target_bar is self.tabs_right.tabBar():
            target_tw = self.tabs_right
        if target_tw is None:
            return
        local_pos = target_bar.mapFromGlobal(drop_pos)
        target_idx = target_bar.tabAt(local_pos)
        if target_idx < 0:
            target_idx = target_tw.count()
        self._move_tab_between_panes(
            source,
            idx,
            target_tw,
            target_insert_idx=target_idx,
            emphasize=True,
        )
        self._hide_tab_drop_indicator()

    def _insert_existing_tab(
        self,
        browser: "FileBrowser",
        tab_widget: QTabWidget,
        insert_idx: int | None = None,
    ) -> int:
        """Nimmt einen bestehenden Browser-Widget auf und gibt den Index zurück."""
        tw = tab_widget
        browser.set_window_drag_enabled(self._custom_chrome)
        browser.path_changed.connect(self._path_changed)
        browser.request_add_fav.connect(self.fav_panel.add_current)
        browser.request_new_tab.connect(lambda t=tw: self._new_tab(t))
        browser.request_open_path_in_new_tab.connect(lambda p, t=tw: self._add_tab(p, t))
        if self._custom_chrome:
            browser.request_window_drag_start.connect(self._window_drag_start)
            browser.request_window_drag_move.connect(self._window_drag_move)
            browser.request_window_drag_end.connect(self._window_drag_end)
        browser.selection_changed.connect(self._on_selection_changed)
        name = Path(browser.current_path).name or "/"
        if insert_idx is None or insert_idx < 0 or insert_idx > tw.count():
            idx = tw.addTab(browser, name)
        else:
            idx = tw.insertTab(insert_idx, browser, name)
        self._add_close_btn(tw, idx, browser)
        tw.setCurrentIndex(idx)
        self._update_tab_bar_visibility()
        return idx

    def _emphasize_moved_tab(self, tab_widget: QTabWidget, idx: int):
        """Markiert einen frisch verschobenen Tab kurz sichtbar (ohne Textänderung)."""
        if idx < 0 or idx >= tab_widget.count():
            return
        bar = tab_widget.tabBar()
        original_color = bar.tabTextColor(idx)
        bar.setTabTextColor(idx, tab_widget.palette().color(tab_widget.palette().ColorRole.Highlight))

        def _clear_mark():
            if idx < tab_widget.count():
                bar.setTabTextColor(idx, original_color)

        QTimer.singleShot(900, _clear_mark)

    def _update_tab_bar_visibility(self):
        """Im Split immer beide Tab-Leisten zeigen; sonst links auto-hide."""
        in_split = self.tabs_right.isVisible()
        self.tabs.setTabBarAutoHide(not in_split)
        self.tabs_right.setTabBarAutoHide(not in_split)

    def _tab_drop_indicator(self):
        if not hasattr(self, "_drop_indicator"):
            w = QWidget(self)
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            w.setStyleSheet(
                "background: palette(highlight);"
                "border-radius: 1px;"
            )
            w.hide()
            self._drop_indicator = w
        return self._drop_indicator

    def _hide_tab_drop_indicator(self):
        if hasattr(self, "_drop_indicator"):
            self._drop_indicator.hide()

    def _update_tab_drop_indicator(self, target_bar, global_pos):
        """Zeigt eine Einfügelinie im Ziel-TabBar bereits während des Ziehens."""
        if target_bar is None or global_pos is None:
            self._hide_tab_drop_indicator()
            return
        if target_bar not in (self.tabs.tabBar(), self.tabs_right.tabBar()):
            self._hide_tab_drop_indicator()
            return

        local = target_bar.mapFromGlobal(global_pos)
        idx = target_bar.tabAt(local)
        tab_h = target_bar.height()

        if idx < 0:
            x_local = 1 if target_bar.count() == 0 else target_bar.tabRect(target_bar.count() - 1).right() + 1
        else:
            rect = target_bar.tabRect(idx)
            x_local = rect.left() if local.x() < rect.center().x() else rect.right() + 1

        top_left_global = target_bar.mapToGlobal(QPoint(x_local - 1, 2))
        top_left = self.mapFromGlobal(top_left_global)

        indicator = self._tab_drop_indicator()
        indicator.setGeometry(top_left.x(), top_left.y(), 3, max(8, tab_h - 4))
        indicator.show()

    def _current_browser_in(self, tw: QTabWidget) -> "FileBrowser | None":
        """Gibt den aktiven Browser im angegebenen TabWidget zurück."""
        w = tw.currentWidget()
        return w if isinstance(w, FileBrowser) else None

    @property
    def current_browser(self) -> "FileBrowser | None":
        """Gibt den aktiven Browser zurück — bevorzugt das zuletzt verwendete Pane."""
        # Linke Pane ist primär
        return self._current_browser_in(self.tabs)

    def focusNextPrevChild(self, next_: bool) -> bool:
        """3-Stop Tab-Reihenfolge: Favoriten → Ordnerinhalt → Suche → zurück."""
        cur = self.current_browser
        if cur is None:
            return super().focusNextPrevChild(next_)
        active_view = cur.icon_view if cur._view_stack.currentIndex() == 1 else cur.tree
        stops = [self.fav_panel.view, cur.search, active_view]
        focused = QApplication.focusWidget()
        try:
            idx = stops.index(focused)
        except ValueError:
            # Fokus ist woanders (z. B. Adressleiste) → zum ersten Stop
            stops[0].setFocus(Qt.FocusReason.TabFocusReason)
            return True
        next_idx = (idx + (1 if next_ else -1)) % len(stops)
        stops[next_idx].setFocus(Qt.FocusReason.TabFocusReason)
        return True

    def _fav_navigate(self, path: str):
        cur = self.current_browser
        if cur:
            cur.navigate(path)
            cur.focus_and_select_first()

    def _tab_changed(self, idx: int, tab_widget: QTabWidget | None = None):
        tw = tab_widget or self.tabs
        browser = tw.widget(idx)
        if isinstance(browser, FileBrowser):
            self._path_changed(browser.current_path)
            if hasattr(self, "_a_show_hidden"):
                self._a_show_hidden.setChecked(browser.show_hidden())
            if hasattr(self, "_a_folders_top"):
                self._a_folders_top.setChecked(browser.model.folders_always_top())

    def _toggle_split(self):
        """Schaltet Dual-Pane (rechte Tab-Gruppe) ein/aus (F8)."""
        visible = not self.tabs_right.isVisible()
        self.tabs_right.setVisible(visible)
        if visible:
            if self.tabs_right.count() == 0:
                # Rechte Pane mit aktuellem Ordner initialisieren
                cur = self.current_browser
                self._add_tab(cur.current_path if cur else str(Path.home()), self.tabs_right)
            # Splitter gleichmäßig aufteilen
            total = self._pane_splitter.width()
            self._pane_splitter.setSizes([total // 2, total // 2])
        self._update_tab_bar_visibility()
        s = QSettings(ORG_NAME, "MainWindow")
        s.setValue(SK_SPLITTER_PANE, self._pane_splitter.saveState())

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
            (Qt.Key.Key_Space, self._toggle_preview),
        ]
        if sys.platform == "darwin":
            win_pairs.append((
                QKeySequence("Meta+Shift+N"),
                lambda: self.current_browser and self.current_browser._new_file(),
            ))
            win_pairs.append((
                QKeySequence("Meta+Backspace"),
                lambda: self.current_browser and self.current_browser._delete(),
            ))
            win_pairs.append((
                QKeySequence("Meta+Shift+Period"),
                lambda: self.current_browser and self.current_browser._toggle_hidden(),
            ))
        else:
            win_pairs.append((
                QKeySequence("Ctrl+Shift+N"),
                lambda: self.current_browser and self.current_browser._new_file(),
            ))
            win_pairs.append((
                QKeySequence("Ctrl+Backspace"),
                lambda: self.current_browser and self.current_browser._delete(),
            ))
            win_pairs.append((
                QKeySequence("Ctrl+Shift+H"),
                lambda: self.current_browser and self.current_browser._toggle_hidden(),
            ))

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
        if visible:
            # Splitter-Breiten neu verteilen: Preview bekommt seine bevorzugte Breite
            total = self.splitter.width()
            pw = self.preview._preferred_width
            fav_w = self.splitter.sizes()[0]
            self.splitter.setSizes([fav_w, max(400, total - fav_w - pw), pw])
        s = QSettings(ORG_NAME, "MainWindow")
        s.setValue(SK_PREVIEW_VISIBLE, visible)

    def _set_view(self, mode: str):
        """Wechselt den aktiven Browser zur angegeben Ansicht (Liste/Icon)."""
        cur = self.current_browser
        if cur is None:
            return
        if mode == "icon" and cur._view_stack.currentIndex() == 0:
            cur._toggle_view_mode()
        elif mode == "list" and cur._view_stack.currentIndex() == 1:
            cur._toggle_view_mode()

    def _on_selection_changed(self, path: str):
        """Aktualisiert die Vorschau wenn sich die Auswahl ändert."""
        if self.preview.isVisible():
            if path:
                self.preview.show_path(path)
            else:
                self.preview.clear_preview()

    def _build_menu(self):
        mb = self.menuBar()
        if sys.platform.startswith("linux"):
            # Verhindert Probleme mit globaler Menü-Integration (z. B. sofortiges
            # Auslösen des ersten Menüeintrags beim Öffnen auf einigen Distros).
            mb.setNativeMenuBar(False)

        # ── Datei ─────────────────────────────────────────────────────────────
        m = mb.addMenu("Datei")
        self._a(m, "Neuer Ordner",  "Ctrl+N",  lambda: self.current_browser and self.current_browser._new_folder())
        # Shortcut läuft über QShortcut in _install_window_shortcuts (zuverlässig mit Fokus in Liste/Favoriten).
        _nf_hint = "Cmd+Shift+N" if sys.platform == "darwin" else "Ctrl+Shift+N"
        self._a(m, f"Neue Datei\t{_nf_hint}", "", lambda: self.current_browser and self.current_browser._new_file())
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
        if sys.platform == "darwin":
            self._a(m, "In Papierkorb\tCmd+Backspace", "", lambda: self.current_browser and self.current_browser._delete())
        else:
            trash_action = self._a(m, "In Papierkorb\tDelete  ·  Ctrl+Backspace", "", lambda: self.current_browser and self.current_browser._delete())
            trash_action.setShortcut(QKeySequence("Delete"))
        m.addSeparator()
        self._a(m, "Rückgängig",           "Ctrl+Z",  lambda: self.current_browser and self.current_browser._undo())

        # ── Ansicht ───────────────────────────────────────────────────────────
        m_view = mb.addMenu("Ansicht")
        self._a(m_view, "Aktualisieren",    "F5",            lambda: self.current_browser and self.current_browser.refresh())
        self._a(m_view, "Liste",            "Ctrl+Shift+L",  lambda: self._set_view("list"))
        self._a(m_view, "Icon-Raster",      "Ctrl+Shift+I",  lambda: self._set_view("icon"))
        m_view.addSeparator()
        self._a(m_view, "Split-Pane",       "F8",            self._toggle_split)
        self._a(m_view, "Vorschau",         "F9",            self._toggle_preview)
        m_view.addSeparator()
        _hidden_hint = "Cmd+Shift+." if sys.platform == "darwin" else "Ctrl+Shift+H"
        self._a_show_hidden = self._a(
            m_view,
            f"Versteckte Dateien\t{_hidden_hint}",
            "",
            lambda enabled: self.current_browser and self.current_browser.set_show_hidden(enabled),
        )
        self._a_show_hidden.setCheckable(True)
        self._a_show_hidden.setChecked(False)
        self._a_folders_top = self._a(m_view, "Ordner immer oben")
        self._a_folders_top.setCheckable(True)
        self._a_folders_top.setChecked(True)
        self._a_folders_top.triggered.connect(
            lambda enabled: self.current_browser and self.current_browser.set_folders_always_top(enabled)
        )
        if self.current_browser is not None:
            self._a_show_hidden.setChecked(self.current_browser.show_hidden())
        if self.current_browser is not None:
            self._a_folders_top.setChecked(self.current_browser.model.folders_always_top())

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
        s.setValue(SK_GEOMETRY,      self.saveGeometry())
        s.setValue(SK_SPLITTER_MAIN, self.splitter.saveState())
        s.setValue(SK_SPLITTER_PANE, self._pane_splitter.saveState())
        cur = self.current_browser
        if cur:
            s.setValue(SK_LAST_PATH, cur.current_path)
        super().closeEvent(event)
