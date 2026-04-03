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
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QToolButton,
    QFrame, QMenu, QMessageBox, QInputDialog, QAbstractItemView,
    QHeaderView, QFileDialog, QSizePolicy, QProgressDialog, QDialog,
    QApplication,
)
from PySide6.QtCore import (
    Qt, QModelIndex, Signal, QTimer, QSettings, QUrl, QDir, QFileInfo, QSize,
    QItemSelectionModel, QMimeData,
)
from PySide6.QtGui import QDesktopServices, QPalette, QKeySequence, QShortcut

from config import ORG_NAME, SK_SHOW_HIDDEN, SK_COL_WIDTHS, SK_COL_SORT_COL, SK_COL_SORT_ORDER
from models import ExplorerModel
from workers import UndoStack, CopyWorker
from treeview import ExplorerTreeView
from addressbar import AddressBar
from fileops import build_ops, safe_trash, reveal_in_filemanager, get_clipboard_paths
from dialogs import BatchRenameDialog


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
        self._select_first_on_load: bool = False

        self._build_ui()
        self._install_shortcuts()
        self.navigate(start_path or str(Path.home()))

    # ── UI-Aufbau ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        tb = QWidget()
        tb.setFixedHeight(38)
        tbl = QHBoxLayout(tb)
        tbl.setContentsMargins(6, 3, 6, 3)
        tbl.setSpacing(4)

        def nav_btn(tip, arrow=None, text=None):
            btn = QToolButton()
            btn.setToolTip(tip)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if arrow:
                btn.setArrowType(arrow)
            if text:
                btn.setText(text)
                f = btn.font()
                if f.pointSize() > 0:
                    f.setPointSize(13)
                btn.setFont(f)
            btn.setFixedSize(28, 28)
            return btn

        self.btn_back    = nav_btn("Zurück  (Alt+←)",       Qt.ArrowType.LeftArrow)
        self.btn_forward = nav_btn("Vor  (Alt+→)",           Qt.ArrowType.RightArrow)
        self.btn_up      = nav_btn("Übergeordnet  (Alt+↑)",  text="↑")
        self.btn_reload  = nav_btn("Aktualisieren  (F5)",    text="↺")

        self.btn_back.setEnabled(False)
        self.btn_forward.setEnabled(False)

        self.btn_back.clicked.connect(self.go_back)
        self.btn_forward.clicked.connect(self.go_forward)
        self.btn_up.clicked.connect(self.go_up)
        self.btn_reload.clicked.connect(self.refresh)

        self.addr = AddressBar()
        self.addr.path_entered.connect(self.navigate)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Suche …")
        self.search.setFixedWidth(170)
        self.search.textChanged.connect(self._on_search)

        tbl.addWidget(self.btn_back)
        tbl.addWidget(self.btn_forward)
        tbl.addWidget(self.btn_up)
        tbl.addWidget(self.btn_reload)
        tbl.addSpacing(4)
        tbl.addWidget(self.addr, 1)
        tbl.addWidget(self.search)
        root.addWidget(tb)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        self.model = ExplorerModel()

        # Versteckte-Dateien-Zustand aus QSettings wiederherstellen
        s = QSettings(ORG_NAME, "FileBrowser")
        if s.value("show_hidden", False, type=bool):
            self.model.setFilter(self.model.filter() | QDir.Filter.Hidden)

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

        root.addWidget(self.tree, 1)

        self.status = QLabel()
        self.status.setFixedHeight(20)
        f = self.status.font()
        if f.pointSize() > 0:
            f.setPointSize(10)
        self.status.setFont(f)
        self.status.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.status.setContentsMargins(8, 0, 8, 0)
        root.addWidget(self.status)

    # ── Tastaturkürzel ────────────────────────────────────────────────────────
    def _install_shortcuts(self):
        # Nur Shortcuts die NICHT im Menü und NICHT im Fenster definiert sind.
        # Ctrl+F, Ctrl+L, F4 sind in MainWindow._install_window_shortcuts (WindowShortcut),
        # damit sie auch aus der Favoritenleiste heraus funktionieren.
        pairs = [
            (Qt.Key.Key_Backspace,  self.go_up),      # Alt+Up ist im Menü
            (Qt.Key.Key_Return,     self._open_sel),
            (Qt.Key.Key_Enter,      self._open_sel),
            (Qt.Key.Key_Escape,     self._escape),
        ]
        for combo, slot in pairs:
            sc = QShortcut(QKeySequence(combo), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

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
        if self._pending_select:
            sel = self.model.index(self._pending_select)
            if sel.isValid():
                self.tree._select(sel)
            self._pending_select = None
        elif self._select_first_on_load:
            self._select_first_on_load = False
            first = self.model.index(0, 0, self.tree.rootIndex())
            if first.isValid():
                self.tree._select(first)
            self.tree.setFocus()

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
        sel = self.tree.selectionModel().selectedRows()
        try:
            total = len(os.listdir(self._cur))
        except PermissionError:
            self.status.setText("Zugriff verweigert")
            return
        if sel:
            self.status.setText(f"{len(sel)} Element(e) ausgewählt  ·  {total} insgesamt")
        else:
            self.status.setText(f"{total} Elemente")

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
        s.setValue(SK_COL_SORT_ORDER, int(hdr.sortIndicatorOrder()))

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
        sort_col   = s.value(SK_COL_SORT_COL, 0, type=int)
        sort_order = s.value(SK_COL_SORT_ORDER, int(Qt.SortOrder.AscendingOrder), type=int)
        self.tree.sortByColumn(sort_col, Qt.SortOrder(sort_order))

    # ── Auswahl-Hilfsmethoden ─────────────────────────────────────────────────
    def _sel_rows(self) -> list[QModelIndex]:
        return self.tree.selectionModel().selectedRows(0)

    def _sel_paths(self) -> list[str]:
        return [self.model.filePath(i) for i in self._sel_rows()]

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
        self._worker.error.connect(lambda msg: QMessageBox.warning(self, "Fehler", msg))

        def on_finished(dst_paths):
            dlg.close()
            if mode == "copy":
                self._undo_stack.push({"op": "copy", "paths": dst_paths})
            else:
                pairs = [(dst, src) for (src, _), dst in zip(ops_copy, dst_paths)]
                self._undo_stack.push({"op": "move", "pairs": pairs})
            self.refresh()

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
        names = [Path(p).name for p in paths]
        text  = "\n".join(names[:6])
        if len(names) > 6:
            text += f"\n… und {len(names) - 6} weitere"
        reply = QMessageBox.question(
            self, "In Papierkorb legen",
            f"{len(paths)} Element(e) in den Papierkorb legen?\n\n{text}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
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

    # ── Suche (Groß-/Kleinschreibung ignorieren) ──────────────────────────────
    def _on_search(self, text: str):
        if text:
            t = text.lower()
            # Doppelter Filter fängt beide Schreibweisen ab (macOS APFS case-insensitive)
            self.model.setNameFilters([f"*{t}*", f"*{t.upper()}*", f"*{text}*"])
            self.model.setNameFilterDisables(False)
        else:
            self.model.setNameFilters([])
            self.model.setNameFilterDisables(True)

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
        index = self.tree.indexAt(pos)
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
            a_hidden = menu.addAction("Versteckte Dateien anzeigen")
            a_hidden.setCheckable(True)
            a_hidden.setChecked(bool(self.model.filter() & QDir.Filter.Hidden))
            a_hidden.triggered.connect(self._toggle_hidden)
            menu.addSeparator()
            a_fav = menu.addAction("Aktuellen Ordner zu Favoriten")
            a_fav.triggered.connect(lambda: self.request_add_fav.emit(self._cur))

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _toggle_hidden(self):
        f = self.model.filter()
        if f & QDir.Filter.Hidden:
            self.model.setFilter(f & ~QDir.Filter.Hidden)
            show = False
        else:
            self.model.setFilter(f | QDir.Filter.Hidden)
            show = True
        # Zustand dauerhaft speichern
        s = QSettings(ORG_NAME, "FileBrowser")
        s.setValue("show_hidden", show)

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
        """Wechselt zwischen Listen- und Icon-Raster-Ansicht (implementiert in Task 20)."""
        pass
