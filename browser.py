"""
browser.py — FileBrowser: ein Tab-Inhalt mit Navigation, Dateiliste und Operationen.

Enthält: Navigation (history, back/forward/up), Dateioperationen (copy/move/delete/
rename/batch-rename/paste/undo), Suche, Kontextmenü, Status-Zeile.
"""
import os
import sys
import shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QFrame, QMenu, QMessageBox, QInputDialog, QAbstractItemView,
    QHeaderView, QFileDialog, QProgressDialog, QDialog,
    QApplication, QListView, QStackedWidget,
)
from PySide6.QtCore import (
    Qt, QModelIndex, Signal, QTimer, QSettings, QUrl, QDir, QFileInfo, QSize,
    QItemSelectionModel, QMimeData, QEvent,
)
from PySide6.QtGui import QDesktopServices, QPalette, QKeySequence, QShortcut

from config import (
    ORG_NAME, SK_SHOW_HIDDEN, SK_COL_WIDTHS, SK_COL_SORT_COL, SK_COL_SORT_ORDER,
    SK_VIEW_MODE, SK_FOLDERS_TOP,
)
from models import ExplorerModel, ExplorerProxyModel
from workers import UndoStack, CopyWorker
from treeview import ExplorerTreeView
from addressbar import BreadcrumbBar
from fileops import build_ops, safe_trash, reveal_in_filemanager, get_clipboard_paths
from dialogs import BatchRenameDialog
from toolbar import BrowserToolbar
from search_worker import SearchWorker
from logger import log_exception


def _show_macos_fda_dialog(parent=None):
    """Zeigt einmalig den Full Disk Access Dialog (macOS). Importiert aus main."""
    try:
        import main as _m
        _m._macos_show_fda_dialog(parent)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Haupt-Browser-Widget
# ──────────────────────────────────────────────────────────────────────────────
class FileBrowser(QWidget):
    path_changed      = Signal(str)
    request_add_fav   = Signal(str)
    request_new_tab   = Signal()
    request_open_path_in_new_tab = Signal(str)
    request_window_drag_start = Signal(object)
    request_window_drag_move = Signal(object)
    request_window_drag_end = Signal()
    selection_changed = Signal(str)   # Pfad des ausgewählten Elements oder ""

    def __init__(self, start_path: str | None = None, parent=None):
        super().__init__(parent)
        self._history: list[str] = []
        self._hist_pos = -1
        self._cur: str = str(Path.home())
        self._clip_mode: str | None = None
        self._clip_paths: list[str] = []
        self._undo_stack = UndoStack()
        self._worker: CopyWorker | None = None
        self._pending_select: str | None = None
        self._pending_row: int | None = None
        self._select_first_on_load: bool = False
        self._op_message: str = ""

        self._build_ui()
        s = QSettings(ORG_NAME, "FileBrowser")
        if s.value(SK_VIEW_MODE, "list") == "icon":
            self._toggle_view_mode()
        self._search_worker: SearchWorker | None = None
        self._search_results: list[str] = []
        self._in_search_mode: bool = False
        self._install_shortcuts()
        self.navigate(start_path or str(Path.home()))

    def set_window_drag_enabled(self, enabled: bool):
        self.toolbar.set_drag_area_enabled(enabled)

    # ── UI-Aufbau ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ───────────────────────────────────────────────────────────────
        self.toolbar = BrowserToolbar()
        self.toolbar.back_clicked.connect(self.go_back)
        self.toolbar.forward_clicked.connect(self.go_forward)
        self.toolbar.up_clicked.connect(self.go_up)
        self.toolbar.reload_clicked.connect(self.refresh)
        self.toolbar.new_folder_clicked.connect(self._new_folder)
        self.toolbar.view_toggle.connect(self._toggle_view_mode)
        self.toolbar.new_tab_clicked.connect(self.request_new_tab.emit)
        self.toolbar.window_drag_start.connect(self.request_window_drag_start.emit)
        self.toolbar.window_drag_move.connect(self.request_window_drag_move.emit)
        self.toolbar.window_drag_end.connect(self.request_window_drag_end.emit)
        root.addWidget(self.toolbar)

        # Kompatibilitäts-Aliase: _update_nav_btns() referenziert btn_back/btn_forward
        self.btn_back    = self.toolbar.btn_back
        self.btn_forward = self.toolbar.btn_forward

        # ── Adresszeile ───────────────────────────────────────────────────────────
        addr_row = QWidget()
        addr_row.setFixedHeight(38)
        addr_layout = QHBoxLayout(addr_row)
        addr_layout.setContentsMargins(6, 3, 6, 3)
        addr_layout.setSpacing(4)

        self.addr = BreadcrumbBar()
        self.addr.path_entered.connect(self.navigate)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Suche …")
        self.search.setFixedWidth(170)
        self.search.textChanged.connect(self._on_search)

        addr_layout.addWidget(self.addr, 1)
        addr_layout.addWidget(self.search)
        root.addWidget(addr_row)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        self._fs_model = ExplorerModel()
        self.model = ExplorerProxyModel(self._fs_model, self)

        # Versteckte-Dateien-Zustand aus QSettings wiederherstellen
        s = QSettings(ORG_NAME, "FileBrowser")
        if s.value(SK_SHOW_HIDDEN, False, type=bool):
            f = self.model.filter()
            self.model.setFilter((f | QDir.Filter.Hidden) & ~QDir.Filter.NoDotAndDotDot)
        self.model.set_folders_always_top(s.value(SK_FOLDERS_TOP, True, type=bool))

        self.tree = ExplorerTreeView()
        self.tree._current_path = self._cur
        self.tree.setModel(self.model)
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._ctx_menu)
        self.tree.doubleClicked.connect(self._dbl_click)
        self.tree.selectionModel().selectionChanged.connect(self._sel_changed)
        self.tree.files_dropped.connect(self._on_files_dropped)
        self.tree.open_in_new_tab.connect(self.request_open_path_in_new_tab.emit)

        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        # Standardbreiten setzen, dann gespeicherte Einstellungen wiederherstellen
        hdr.resizeSection(0, 280)
        hdr.resizeSection(1, 145)
        hdr.resizeSection(2, 80)
        hdr.resizeSection(3, 100)
        self.restore_column_state()

        # Spaltenbreite und Sortierung bei Änderung persistieren
        hdr.sectionResized.connect(lambda col, old, new: self.save_column_state())
        hdr.sortIndicatorChanged.connect(lambda col, order: self.save_column_state())

        # Stack: Index 0 = Listenmodus, Index 1 = Icon-Modus
        self._view_stack = QStackedWidget()

        # Seite 0: bestehende Baumansicht
        self._view_stack.addWidget(self.tree)

        # Seite 1: Icon-Raster
        self.icon_view = QListView()
        self.icon_view.setViewMode(QListView.ViewMode.IconMode)
        self.icon_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.icon_view.setIconSize(QSize(64, 64))
        self.icon_view.setGridSize(QSize(90, 90))
        self.icon_view.setSpacing(4)
        self.icon_view.setUniformItemSizes(True)
        self.icon_view.setModel(self.model)
        self.icon_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.icon_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.icon_view.customContextMenuRequested.connect(self._ctx_menu)
        self.icon_view.doubleClicked.connect(self._dbl_click)
        self.icon_view.selectionModel().selectionChanged.connect(self._sel_changed)
        self.icon_view.installEventFilter(self)
        self._view_stack.addWidget(self.icon_view)

        root.addWidget(self._view_stack, 1)

        self.status_row = QWidget()
        self.status_row.setFixedHeight(20)
        status_layout = QHBoxLayout(self.status_row)
        status_layout.setContentsMargins(8, 0, 8, 0)
        status_layout.setSpacing(8)

        self.status = QLabel()
        f = self.status.font()
        if f.pointSize() > 0:
            f.setPointSize(10)
        self.status.setFont(f)
        self.status.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.status.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        self.status_op = QLabel()
        self.status_op.setFont(f)
        self.status_op.setStyleSheet("color: white;")
        self.status_op.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        status_layout.addWidget(self.status, 1)
        status_layout.addWidget(self.status_op, 0)
        root.addWidget(self.status_row)

    # ── Event-Filter (Icon-Raster: Pfeil-Wrap-Around) ─────────────────────────
    def eventFilter(self, obj, event):
        if obj is self.icon_view and event.type() == QEvent.Type.KeyPress:
            root  = self.icon_view.rootIndex()
            count = self.model.rowCount(root)
            cur   = self.icon_view.currentIndex().row()
            key   = event.key()
            if key == Qt.Key.Key_Down and count and cur >= count - 1:
                first = self.model.index(0, 0, root)
                self.icon_view.setCurrentIndex(first)
                self.icon_view.selectionModel().select(
                    first,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
                return True
            if key == Qt.Key.Key_Up and count and cur <= 0:
                last = self.model.index(count - 1, 0, root)
                self.icon_view.setCurrentIndex(last)
                self.icon_view.selectionModel().select(
                    last,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
                return True
        if obj is self.icon_view and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.MiddleButton:
                idx = self.icon_view.indexAt(event.position().toPoint())
                if idx.isValid():
                    path = self.model.filePath(idx)
                    if os.path.isdir(path):
                        self.request_open_path_in_new_tab.emit(path)
                        return True
        return super().eventFilter(obj, event)

    # ── Tastaturkürzel ────────────────────────────────────────────────────────
    def _install_shortcuts(self):
        # Nur Shortcuts die NICHT im Menü und NICHT im Fenster definiert sind.
        # Ctrl+F, Ctrl+L, F4 sind in MainWindow._install_window_shortcuts (WindowShortcut),
        # damit sie auch aus der Favoritenleiste heraus funktionieren.

        # Return/Enter/Backspace: nur auf den Dateilisten-Widgets (WidgetShortcut),
        # damit QLineEdit-Felder (Adressleiste, Suche) den Tastendruck selbst verarbeiten
        # können und returnPressed ungestört emittiert wird.
        view_pairs = [
            (Qt.Key.Key_Backspace, self.go_up),
            (Qt.Key.Key_Return,    self._open_sel),
            (Qt.Key.Key_Enter,     self._open_sel),
        ]
        for view in (self.tree, self.icon_view):
            for combo, slot in view_pairs:
                sc = QShortcut(QKeySequence(combo), view)
                sc.setContext(Qt.ShortcutContext.WidgetShortcut)
                sc.activated.connect(slot)

        # Escape: breit verfügbar (wird in _escape selbst eingegrenzt)
        sc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(self._escape)

        for seq in ("Ctrl+Return", "Ctrl+Enter", "Meta+Return", "Meta+Enter"):
            sc_new = QShortcut(QKeySequence(seq), self)
            sc_new.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc_new.activated.connect(self._open_sel_in_new_tab)

        # Papierkorb: Cmd+Backspace (macOS) bzw. Delete / Ctrl+Backspace (Win/Linux)
        # liegen in MainWindow (WindowShortcut), damit es auch aus der Favoritenleiste geht.

    # ── Navigation ────────────────────────────────────────────────────────────
    def navigate(self, path: str):
        path = str(Path(path).resolve())
        if not os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        try:
            os.listdir(path)
        except PermissionError:
            if sys.platform == "darwin":
                _show_macos_fda_dialog(self)
            else:
                QMessageBox.warning(self, "Zugriff verweigert",
                                    f"Kein Zugriff auf:\n{path}")
            return
        if not (self._history and self._history[self._hist_pos] == path):
            self._history = self._history[: self._hist_pos + 1]
            self._history.append(path)
            self._hist_pos = len(self._history) - 1
        self._apply(path)

    def _nav_no_hist(self, path: str, select_path: str | None = None):
        self._pending_select = select_path
        self._apply(path)

    def _apply(self, path: str):
        self._cur = path
        self.tree._current_path = path
        self.tree.selectionModel().clearSelection()
        self.model.setRootPath(path)
        QTimer.singleShot(30, lambda: self._set_root_index(path))
        self.addr.setText(path)
        self._update_nav_btns()
        self._update_status()
        self.path_changed.emit(path)

    def _set_root_index(self, path: str):
        idx = self.model.index(path)
        if idx.isValid():
            self.tree.setRootIndex(idx)
            self.icon_view.setRootIndex(idx)
        if self._pending_select:
            sel = self.model.index(self._pending_select)
            if sel.isValid():
                self.tree._select(sel)
                self._pending_row = None
            self._pending_select = None
        elif self._pending_row is not None:
            row = max(0, self._pending_row)
            self._pending_row = None
            target = self.model.index(row, 0, self.tree.rootIndex())
            if not target.isValid():
                count = self.model.rowCount(self.tree.rootIndex())
                if count > 0:
                    target = self.model.index(count - 1, 0, self.tree.rootIndex())
            if target.isValid():
                self.tree._select(target)
        else:
            give_focus = self._select_first_on_load
            self._select_first_on_load = False
            first = self.model.index(0, 0, self.tree.rootIndex())
            if first.isValid():
                self.tree._select(first)
                if give_focus:
                    self.tree.setFocus()
            else:
                # Modell noch nicht geladen → auf directoryLoaded warten
                def _on_dir_loaded(loaded_path, _give_focus=give_focus):
                    if loaded_path == path:
                        try:
                            self.model.directoryLoaded.disconnect(_on_dir_loaded)
                        except RuntimeError:
                            pass
                        if self._pending_row is not None:
                            rr = max(0, self._pending_row)
                            self._pending_row = None
                            f = self.model.index(rr, 0, self.tree.rootIndex())
                            if not f.isValid():
                                c = self.model.rowCount(self.tree.rootIndex())
                                if c > 0:
                                    f = self.model.index(c - 1, 0, self.tree.rootIndex())
                        else:
                            f = self.model.index(0, 0, self.tree.rootIndex())
                        if f.isValid():
                            self.tree._select(f)
                            if _give_focus:
                                self.tree.setFocus()
                self.model.directoryLoaded.connect(_on_dir_loaded)

    def go_back(self):
        if self._hist_pos > 0:
            from_path = self._history[self._hist_pos]
            self._hist_pos -= 1
            self._nav_no_hist(self._history[self._hist_pos], select_path=from_path)

    def go_forward(self):
        if self._hist_pos < len(self._history) - 1:
            self._hist_pos += 1
            self._nav_no_hist(self._history[self._hist_pos])

    def go_up(self):
        p = Path(self._cur).parent
        if str(p) != self._cur:
            self._pending_select = self._cur
            self.navigate(str(p))

    def focus_and_select_first(self):
        """Fokus und ersten Eintrag nach Root-Wechsel setzen (nach dem 30ms-Timer)."""
        self._select_first_on_load = True

    def refresh(self):
        self.model.setRootPath("")
        QTimer.singleShot(80, lambda: self._apply(self._cur))

    @property
    def current_path(self) -> str:
        return self._cur

    def _update_nav_btns(self):
        self.btn_back.setEnabled(self._hist_pos > 0)
        self.btn_forward.setEnabled(self._hist_pos < len(self._history) - 1)

    def _update_status(self):
        """Aktualisiert Statuszeile: Auswahl, Gesamtanzahl, Speicherplatz."""
        active_view = self.icon_view if self._view_stack.currentIndex() == 1 else self.tree
        sel = active_view.selectionModel().selectedRows()
        try:
            total = len(os.listdir(self._cur))
        except PermissionError:
            self.status.setText("Zugriff verweigert")
            return

        if sel:
            sel_text = f"{len(sel)} ausgewählt  ·  {total} Elemente"
        else:
            sel_text = f"{total} Elemente"

        # Speicherplatz des aktuellen Laufwerks
        try:
            usage = shutil.disk_usage(self._cur)
            free_gb  = usage.free  / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            disk_text = f"💾 {free_gb:.1f} GB frei von {total_gb:.1f} GB"
        except Exception:
            disk_text = ""

        parts = [sel_text]
        if disk_text:
            parts.append(disk_text)
        self.status.setText("  ·  ".join(parts))
        self.status_op.setText(self._op_message)

    def _set_operation_message(self, text: str):
        self._op_message = text
        self._update_status()

    def save_column_state(self):
        """Speichert Spaltenbreiten und Sortierung global in QSettings.

        Global = eine einzige Einstellung für alle Ordner und alle Tabs.
        Wird beim Ändern der Spaltenbreite/Sortierung aufgerufen.
        """
        import json
        hdr = self.tree.header()
        widths = [hdr.sectionSize(c) for c in range(4)]
        s = QSettings(ORG_NAME, "FileBrowser")
        s.setValue(SK_COL_WIDTHS, json.dumps(widths))
        s.setValue(SK_COL_SORT_COL, hdr.sortIndicatorSection())
        order = hdr.sortIndicatorOrder()
        order_value = order.value if hasattr(order, "value") else int(order)
        s.setValue(SK_COL_SORT_ORDER, order_value)

    def restore_column_state(self):
        """Stellt Spaltenbreiten und Sortierung aus QSettings wieder her.

        Wird einmalig beim Initialisieren aufgerufen, bevor der erste Ordner geladen wird.
        Wenn keine gespeicherten Einstellungen vorhanden, gelten die Standardbreiten.
        """
        import json
        s = QSettings(ORG_NAME, "FileBrowser")

        # Spaltenbreiten wiederherstellen (Fallback: Standardbreiten aus dem Spec)
        raw = s.value(SK_COL_WIDTHS)
        if raw:
            try:
                widths = json.loads(raw)
                hdr = self.tree.header()
                for col, w in enumerate(widths[:4]):
                    hdr.resizeSection(col, int(w))
            except Exception:
                pass

        # Sortierung wiederherstellen
        sort_col = s.value(SK_COL_SORT_COL, 0, type=int)
        sort_order_raw = s.value(SK_COL_SORT_ORDER, Qt.SortOrder.AscendingOrder.value)
        try:
            sort_order = int(sort_order_raw)
        except (TypeError, ValueError):
            sort_order = Qt.SortOrder.AscendingOrder.value
        self.tree.sortByColumn(sort_col, Qt.SortOrder(sort_order))

    # ── Auswahl-Hilfsmethoden ─────────────────────────────────────────────────
    def _sel_rows(self) -> list[QModelIndex]:
        active_view = self.icon_view if self._view_stack.currentIndex() == 1 else self.tree
        return active_view.selectionModel().selectedRows(0)

    def _sel_paths(self) -> list[str]:
        """Gibt die Pfade aller selektierten Einträge zurück."""
        active_view = self.icon_view if self._view_stack.currentIndex() == 1 else self.tree
        indexes = active_view.selectionModel().selectedIndexes()
        paths = []
        seen = set()
        for idx in indexes:
            if idx.column() == 0:
                p = self.model.filePath(idx)
                if p not in seen:
                    seen.add(p)
                    paths.append(p)
        return paths

    def _sel_changed(self):
        self._update_status()
        paths = self._sel_paths()
        self.selection_changed.emit(paths[0] if len(paths) == 1 else "")

    # ── Drag&Drop zwischen Ordnern ────────────────────────────────────────────
    def _on_files_dropped(self, paths: list[str], dest: str, action: Qt.DropAction):
        """Verarbeitet Drag&Drop von Dateien in einen Unterordner."""
        # Nicht in sich selbst ablegen
        paths = [p for p in paths if p != dest and not dest.startswith(p + os.sep)]
        if not paths:
            return
        # Ctrl gedrückt = Kopieren, sonst Verschieben
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier or action == Qt.DropAction.CopyAction:
            self._do_copy(paths, dest)
        else:
            self._do_move(paths, dest)

    # ── Dateioperationen (intern) ─────────────────────────────────────────────
    def _do_copy(self, src_paths: list[str], dest_dir: str):
        ops = build_ops(src_paths, dest_dir)
        if not ops:
            return
        if len(ops) > 3:
            self._run_worker(ops, "copy")
        else:
            dst_paths = []
            for src, dst in ops:
                try:
                    src_p = Path(src)
                    (shutil.copytree if src_p.is_dir() else shutil.copy2)(src, dst)
                    dst_paths.append(dst)
                except OSError as e:
                    QMessageBox.warning(self, "Fehler", f"Kopieren fehlgeschlagen:\n{e}")
            if dst_paths:
                self._undo_stack.push({"op": "copy", "paths": dst_paths})
            self.refresh()

    def _do_move(self, src_paths: list[str], dest_dir: str):
        ops = build_ops(src_paths, dest_dir)
        if not ops:
            return
        if len(ops) > 3:
            self._run_worker(ops, "move")
        else:
            move_pairs = []
            for src, dst in ops:
                try:
                    shutil.move(src, dst)
                    move_pairs.append((dst, src))  # umgekehrt für Undo
                except OSError as e:
                    QMessageBox.warning(self, "Fehler", f"Verschieben fehlgeschlagen:\n{e}")
            if move_pairs:
                self._undo_stack.push({"op": "move", "pairs": move_pairs})
            self.refresh()

    def _run_worker(self, ops: list[tuple[str, str]], mode: str):
        """Hintergrundthread mit Fortschrittsanzeige für große Operationen."""
        total = len(ops)
        label = "Kopiere" if mode == "copy" else "Verschiebe"
        dlg = QProgressDialog(f"{label} {total} Element(e)…", "Abbrechen", 0, total, self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(400)

        ops_copy = list(ops)  # Closure-Snapshot
        self._worker = CopyWorker(ops_copy, mode)
        self._worker.progress.connect(dlg.setValue)
        self._worker.error.connect(
            lambda msg: (
                log_exception(RuntimeError(msg), f"{mode} worker"),
                QMessageBox.warning(self, "Fehler", msg),
            )
        )
        self._set_operation_message(f"{'Kopieren' if mode == 'copy' else 'Verschieben'} läuft …")

        def on_finished(dst_paths):
            dlg.close()
            if mode == "copy":
                self._undo_stack.push({"op": "copy", "paths": dst_paths})
            else:
                pairs = [(dst, src) for (src, _), dst in zip(ops_copy, dst_paths)]
                self._undo_stack.push({"op": "move", "pairs": pairs})
            self.refresh()
            self._set_operation_message("")

        self._worker.finished_ops.connect(on_finished)
        dlg.canceled.connect(self._worker.requestInterruption)
        self._worker.start()

    # ── Dateioperationen (öffentlich) ─────────────────────────────────────────
    def _open_sel(self):
        paths = self._sel_paths()
        if len(paths) == 1:
            if os.path.isdir(paths[0]):
                self.navigate(paths[0])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(paths[0]))

    def _open_sel_in_new_tab(self):
        paths = self._sel_paths()
        if len(paths) == 1 and os.path.isdir(paths[0]):
            self.request_open_path_in_new_tab.emit(paths[0])

    def _dbl_click(self, index: QModelIndex):
        path = self.model.filePath(index)
        if os.path.isdir(path):
            self.navigate(path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _rename(self):
        rows = self._sel_rows()
        if len(rows) != 1:
            return
        path = self.model.filePath(rows[0])
        old  = Path(path).name
        name, ok = QInputDialog.getText(self, "Umbenennen", "Neuer Name:", text=old)
        if ok and name and name != old:
            new_path = str(Path(path).parent / name)
            try:
                os.rename(path, new_path)
                self._undo_stack.push({"op": "rename", "old": path, "new": new_path})
                self.refresh()
            except OSError as e:
                QMessageBox.warning(self, "Fehler", f"Umbenennen fehlgeschlagen:\n{e}")

    def _batch_rename(self):
        paths = self._sel_paths()
        if len(paths) < 2:
            QMessageBox.information(self, "Mehrfach umbenennen",
                                    "Bitte mindestens 2 Elemente auswählen.")
            return
        dlg = BatchRenameDialog(paths, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        pairs = dlg.renamed_pairs()
        if not pairs:
            return
        undo_pairs = []
        for old_path, new_name in pairs:
            new_path = str(Path(old_path).parent / new_name)
            try:
                os.rename(old_path, new_path)
                undo_pairs.append((new_path, old_path))
            except OSError as e:
                QMessageBox.warning(self, "Fehler", f"Umbenennen fehlgeschlagen:\n{e}")
        if undo_pairs:
            self._undo_stack.push({"op": "batch_rename", "pairs": undo_pairs})
        self.refresh()

    def _delete(self):
        paths = self._sel_paths()
        if not paths:
            return
        # Fokusposition merken, damit nach dem Refresh nicht auf Zeile 0 gesprungen wird.
        active_view = self.icon_view if self._view_stack.currentIndex() == 1 else self.tree
        sel_rows = sorted({i.row() for i in active_view.selectionModel().selectedRows(0)})
        if sel_rows:
            self._pending_row = sel_rows[0]
        names = [Path(p).name for p in paths]
        text  = "\n".join(names[:6])
        if len(names) > 6:
            text += f"\n… und {len(names) - 6} weitere"
        reply = QMessageBox.question(
            self, "In Papierkorb legen",
            f"{len(paths)} Element(e) in den Papierkorb legen?\n\n{text}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for p in paths:
            safe_trash(p, self)
        self.refresh()

    def _copy(self):
        paths = self._sel_paths()
        if paths:
            self._clip_mode  = "copy"
            self._clip_paths = paths
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(p) for p in paths])
            QApplication.clipboard().setMimeData(md)

    def _cut(self):
        paths = self._sel_paths()
        if paths:
            self._clip_mode  = "cut"
            self._clip_paths = paths
            # System-Clipboard ebenfalls setzen (für andere Apps)
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(p) for p in paths])
            QApplication.clipboard().setMimeData(md)

    def _paste(self):
        """Einfügen aus interner oder System-Zwischenablage.

        Bug B2 Fix: Wenn keine interne Zwischenablage vorhanden, wird das
        System-Clipboard gelesen (Finder/Explorer/Terminal-Kopien).
        """
        if self._clip_paths:
            mode = self._clip_mode or "copy"
            srcs = list(self._clip_paths)
            if mode == "cut":
                self._clip_paths = []
                self._clip_mode  = None
            if mode == "copy":
                self._do_copy(srcs, self._cur)
            else:
                self._do_move(srcs, self._cur)
        else:
            # Bug B2 Fix: System-Clipboard lesen (Finder/Explorer/Terminal)
            srcs = get_clipboard_paths()
            if srcs:
                self._do_copy(srcs, self._cur)

    def _undo(self):
        if not self._undo_stack.can_undo():
            QMessageBox.information(self, "Rückgängig", "Nichts zum Rückgängigmachen.")
            return
        entry = self._undo_stack.pop()
        op = entry.get("op")
        try:
            if op == "rename":
                os.rename(entry["new"], entry["old"])
            elif op == "batch_rename":
                for new_p, old_p in entry["pairs"]:
                    os.rename(new_p, old_p)
            elif op == "mkdir":
                path = entry["path"]
                if os.path.isdir(path) and not os.listdir(path):
                    os.rmdir(path)
                else:
                    QMessageBox.warning(self, "Rückgängig",
                                        "Ordner nicht leer – Rückgängig nicht möglich.")
            elif op == "move":
                for dst, src in entry["pairs"]:
                    shutil.move(dst, src)
            elif op == "copy":
                for p in entry["paths"]:
                    p_obj = Path(p)
                    if p_obj.is_dir():
                        shutil.rmtree(p)
                    elif p_obj.exists():
                        os.remove(p)
        except OSError as e:
            QMessageBox.warning(self, "Rückgängig fehlgeschlagen", str(e))
        self.refresh()

    def _new_folder(self):
        name, ok = QInputDialog.getText(
            self, "Neuer Ordner", "Ordnername:", text="Neuer Ordner"
        )
        if ok and name:
            path = os.path.join(self._cur, name)
            try:
                os.makedirs(path)
                self._undo_stack.push({"op": "mkdir", "path": path})
                self.refresh()
            except OSError as e:
                QMessageBox.warning(self, "Fehler", f"Ordner konnte nicht erstellt werden:\n{e}")

    def _new_file(self):
        name, ok = QInputDialog.getText(
            self, "Neue Datei", "Dateiname:", text="Neue Datei.txt"
        )
        if not ok or not name:
            return
        path = os.path.join(self._cur, name)
        if os.path.exists(path):
            QMessageBox.warning(self, "Fehler", f"Datei existiert bereits:\n{path}")
            return
        try:
            Path(path).touch(exist_ok=False)
            self.refresh()
        except OSError as e:
            QMessageBox.warning(self, "Fehler", f"Datei konnte nicht erstellt werden:\n{e}")

    # ── Suche (Groß-/Kleinschreibung ignorieren) ──────────────────────────────
    def _on_search(self, text: str):
        """Startet eine rekursive Suche oder setzt den normalen Modus wieder her."""
        # Laufende Suche abbrechen
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.requestInterruption()
            self._search_worker.wait(200)

        if not text:
            # Zurück zu normalem Ordner-Inhalt
            self._in_search_mode = False
            self.model.setNameFilters([])
            self.model.setNameFilterDisables(True)
            self._apply(self._cur)   # Ordner neu laden
            return

        # Einfacher Filter für den aktuellen Ordner (sofortige Rückmeldung)
        self._in_search_mode = False
        t = text.lower()
        self.model.setNameFilters([f"*{t}*", f"*{t.upper()}*", f"*{text}*"])
        self.model.setNameFilterDisables(False)

        # Rekursive Suche im Hintergrund (ab 3 Zeichen)
        if len(text) >= 3:
            self._start_recursive_search(text)

    def _start_recursive_search(self, term: str):
        """Startet SearchWorker für rekursive Suche."""
        # Bisherige Ergebnisse verwerfen
        self._search_results = []
        self._in_search_mode = True

        self._search_worker = SearchWorker(self._cur, term)
        self._search_worker.result.connect(self._on_search_result)
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.start()

    def _on_search_result(self, path: str):
        """Wird pro gefundenem Ergebnis aufgerufen."""
        self._search_results.append(path)
        # Statuszeile aktualisieren
        self.status.setText(f"Suche … {len(self._search_results)} Treffer")

    def _on_search_finished(self):
        """Suche abgeschlossen — Ergebnisse in Statuszeile anzeigen."""
        n = len(self._search_results)
        self.status.setText(f"{n} Treffer (rekursiv)")

    # ── Fokus-Helfer ──────────────────────────────────────────────────────────
    def _focus_addr(self):
        self.addr.setFocus()
        self.addr.selectAll()

    def _focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def _escape(self):
        if self.search.hasFocus() or self.addr.hasFocus():
            self.search.clear()
            self.tree.setFocus()

    # ── Kontextmenü ──────────────────────────────────────────────────────────
    def _ctx_menu(self, pos):
        # Ermittle die aktive Ansicht (Liste oder Icon-Raster)
        active_view = self.icon_view if self._view_stack.currentIndex() == 1 else self.tree
        index = active_view.indexAt(pos)
        paths = self._sel_paths()
        menu  = QMenu(self)

        if index.isValid() and paths:
            a_open = menu.addAction("Öffnen")
            a_open.triggered.connect(self._open_sel)
            if len(paths) == 1:
                label = {"darwin": "Im Finder anzeigen",
                         "win32":  "Im Explorer anzeigen"}.get(sys.platform, "Im Dateimanager anzeigen")
                a_finder = menu.addAction(label)
                a_finder.triggered.connect(lambda: reveal_in_filemanager(paths[0]))
            # „Öffnen mit…" Untermenü (nur für Einzelauswahl von Dateien)
            if len(paths) == 1 and not os.path.isdir(paths[0]):
                from openwith import get_apps_for_file, open_with
                submenu = menu.addMenu("Öffnen mit …")
                apps = get_apps_for_file(paths[0])
                if apps:
                    for app_name, app_cmd in apps:
                        action = submenu.addAction(app_name)
                        snap_cmd = app_cmd   # Closure-Snapshot
                        snap_path = paths[0]
                        action.triggered.connect(
                            lambda _, p=snap_path, c=snap_cmd: open_with(p, c)
                        )
                else:
                    submenu.addAction("Keine kompatiblen Apps gefunden").setEnabled(False)
            menu.addSeparator()
            a_cut = menu.addAction("Ausschneiden\tCtrl+X")
            a_cut.triggered.connect(self._cut)
            a_copy = menu.addAction("Kopieren\tCtrl+C")
            a_copy.triggered.connect(self._copy)
            menu.addSeparator()
            a_ren = menu.addAction("Umbenennen\tF2")
            a_ren.triggered.connect(self._rename)
            a_ren.setEnabled(len(paths) == 1)
            if len(paths) > 1:
                a_batch = menu.addAction("Mehrfach umbenennen …")
                a_batch.triggered.connect(self._batch_rename)
            a_del = menu.addAction("In Papierkorb legen\tDel")
            a_del.triggered.connect(self._delete)
            menu.addSeparator()
            if len(paths) == 1:
                a_fav = menu.addAction("Zu Favoriten hinzufügen")
                a_fav.triggered.connect(lambda: self.request_add_fav.emit(paths[0]))
            menu.addSeparator()
            a_props = menu.addAction("Eigenschaften")
            a_props.triggered.connect(lambda: self._properties(paths[0]))
        else:
            a_paste = menu.addAction("Einfügen\tCtrl+V")
            a_paste.setEnabled(bool(self._clip_paths))
            a_paste.triggered.connect(self._paste)
            menu.addSeparator()
            a_nf = menu.addAction("Neuer Ordner\tCtrl+N")
            a_nf.triggered.connect(self._new_folder)
            menu.addSeparator()
            a_ref = menu.addAction("Aktualisieren\tF5")
            a_ref.triggered.connect(self.refresh)
            menu.addSeparator()
            hidden_hint = "Cmd+Shift+H" if sys.platform == "darwin" else "Ctrl+H"
            a_hidden = menu.addAction(f"Versteckte Dateien\t{hidden_hint}")
            a_hidden.setCheckable(True)
            a_hidden.setChecked(bool(self.model.filter() & QDir.Filter.Hidden))
            a_hidden.triggered.connect(self._toggle_hidden)
            menu.addSeparator()
            a_fav = menu.addAction("Aktuellen Ordner zu Favoriten")
            a_fav.triggered.connect(lambda: self.request_add_fav.emit(self._cur))

        # Archiv-Aktionen
        if index.isValid() and paths:
            menu.addSeparator()
            a_zip = menu.addAction("Als ZIP komprimieren …")
            a_zip.triggered.connect(self._compress_selection)

            # „Hier entpacken" nur für unterstützte Archiv-Dateien
            if len(paths) == 1:
                suffix = "".join(Path(paths[0]).suffixes).lower()
                if suffix in (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz"):
                    a_extract = menu.addAction("Hier entpacken")
                    a_extract.triggered.connect(lambda: self._extract_archive(paths[0]))

        menu.exec(active_view.viewport().mapToGlobal(pos))

    def _toggle_hidden(self):
        self.set_show_hidden(not self.show_hidden())

    def show_hidden(self) -> bool:
        return bool(self.model.filter() & QDir.Filter.Hidden)

    def set_show_hidden(self, enabled: bool):
        f = self.model.filter()
        if enabled:
            self.model.setFilter((f | QDir.Filter.Hidden) & ~QDir.Filter.NoDotAndDotDot)
        else:
            self.model.setFilter((f & ~QDir.Filter.Hidden) | QDir.Filter.NoDotAndDotDot)
        # Zustand dauerhaft speichern
        s = QSettings(ORG_NAME, "FileBrowser")
        s.setValue(SK_SHOW_HIDDEN, bool(enabled))

    def set_folders_always_top(self, enabled: bool):
        self.model.set_folders_always_top(enabled)
        QSettings(ORG_NAME, "FileBrowser").setValue(SK_FOLDERS_TOP, bool(enabled))
        hdr = self.tree.header()
        self.tree.sortByColumn(hdr.sortIndicatorSection(), hdr.sortIndicatorOrder())

    def sort_by_modified_date(self, newest_first: bool = True):
        """Sortiert nach Änderungsdatum (wirkt auf Liste und Icon-Ansicht)."""
        order = (
            Qt.SortOrder.DescendingOrder if newest_first
            else Qt.SortOrder.AscendingOrder
        )
        self.tree.sortByColumn(1, order)

    def _properties(self, path: str):
        fi = QFileInfo(path)
        lines = [
            f"Name:       {fi.fileName()}",
            f"Pfad:       {fi.absoluteFilePath()}",
            f"Art:        {'Ordner' if fi.isDir() else (fi.suffix().upper() + '-Datei' if fi.suffix() else 'Datei')}",
        ]
        if not fi.isDir():
            lines.append(f"Größe:      {ExplorerModel._fmt_size(fi.size())}")
        lines += [
            f"Erstellt:   {fi.birthTime().toString('dd.MM.yyyy  HH:mm')}",
            f"Geändert:   {fi.lastModified().toString('dd.MM.yyyy  HH:mm')}",
            f"Lesbar:     {'Ja' if fi.isReadable() else 'Nein'}",
            f"Schreibbar: {'Ja' if fi.isWritable() else 'Nein'}",
        ]
        QMessageBox.information(self, "Eigenschaften", "\n".join(lines))

    def _toggle_view_mode(self):
        """Wechselt zwischen Listen- und Icon-Raster-Ansicht."""
        if self._view_stack.currentIndex() == 0:
            # Wechsel zu Icon-Modus
            self._view_stack.setCurrentIndex(1)
            self.icon_view.setRootIndex(self.tree.rootIndex())
            mode = "icon"
        else:
            # Wechsel zu Listen-Modus
            self._view_stack.setCurrentIndex(0)
            mode = "list"

        # Persistieren
        s = QSettings(ORG_NAME, "FileBrowser")
        s.setValue(SK_VIEW_MODE, mode)

    def _compress_selection(self):
        """Komprimiert die Auswahl als ZIP im aktuellen Ordner."""
        paths = self._sel_paths()
        if not paths:
            return

        # Standard-Name: erster Dateiname + .zip
        default_name = Path(paths[0]).stem + ".zip"
        dest = str(Path(self._cur) / default_name)
        # Konflikt-Auflösung: (1), (2) etc. anhängen
        i = 1
        while Path(dest).exists():
            dest = str(Path(self._cur) / f"{Path(paths[0]).stem} ({i}).zip")
            i += 1

        dlg = QProgressDialog(f"Komprimiere {len(paths)} Element(e) …", "Abbrechen", 0, 100, self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(400)

        from PySide6.QtCore import QThread, Signal as _Signal

        class _ZipThread(QThread):
            done = _Signal(bool, bool)   # ok, cancelled
            progress = _Signal(int, int)  # current, total

            def __init__(self, srcs, dst):
                super().__init__()
                self._srcs, self._dst = srcs, dst

            def run(self):
                from fileops import compress_to_zip
                self._cancelled = False

                def _on_progress(current: int, total: int):
                    self.progress.emit(current, total)
                    if self.isInterruptionRequested():
                        self._cancelled = True
                        return False
                    return True

                ok = compress_to_zip(self._srcs, self._dst, progress_callback=_on_progress)
                if self.isInterruptionRequested():
                    self._cancelled = True
                self.done.emit(ok, self._cancelled)

        self._zip_thread = _ZipThread(paths, dest)
        self._set_operation_message("ZIP-Komprimierung läuft …")

        def _on_progress(current: int, total: int):
            if dlg.maximum() != max(1, total):
                dlg.setRange(0, max(1, total))
            dlg.setValue(current)

        def _on_done(ok: bool, cancelled: bool):
            dlg.close()
            self.refresh()
            self._set_operation_message("")
            if (not ok) and (not cancelled):
                QMessageBox.warning(self, "Fehler", "Komprimierung fehlgeschlagen.")

        self._zip_thread.progress.connect(_on_progress)
        self._zip_thread.done.connect(_on_done)
        dlg.canceled.connect(self._zip_thread.requestInterruption)
        self._zip_thread.start()

    def _extract_archive(self, path: str):
        """Entpackt ein Archiv in den aktuellen Ordner."""
        from fileops import extract_archive
        self._set_operation_message("Entpacken läuft …")
        ok = extract_archive(path, self._cur)
        self._set_operation_message("")
        if ok:
            self.refresh()
        else:
            QMessageBox.warning(self, "Fehler",
                                f"Entpacken fehlgeschlagen oder Format nicht unterstützt:\n{path}")
