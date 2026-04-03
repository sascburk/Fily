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


# ──────────────────────────────────────────────────────────────────────────────
# Favoriten-Modell


# ──────────────────────────────────────────────────────────────────────────────
# Adressleiste
# ──────────────────────────────────────────────────────────────────────────────
class AddressBar(QLineEdit):
    path_entered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Pfad eingeben …")
        self.returnPressed.connect(self._commit)

    def _commit(self):
        p = self.text().strip()
        if os.path.exists(p):
            self.path_entered.emit(p)
        else:
            QMessageBox.warning(self, "Pfad nicht gefunden",
                                f"Der Pfad existiert nicht:\n{p}")
        self.clearFocus()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.clearFocus()
        super().keyPressEvent(e)


# ──────────────────────────────────────────────────────────────────────────────
# Haupt-Browser-Widget
# ──────────────────────────────────────────────────────────────────────────────
class FileBrowser(QWidget):
    path_changed    = Signal(str)
    request_add_fav = Signal(str)

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
        hdr.resizeSection(0, 280)
        hdr.resizeSection(1, 145)
        hdr.resizeSection(2, 80)
        hdr.resizeSection(3, 100)

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
                _macos_show_fda_dialog(self)
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

    # ── Auswahl-Hilfsmethoden ─────────────────────────────────────────────────
    def _sel_rows(self) -> list[QModelIndex]:
        return self.tree.selectionModel().selectedRows(0)

    def _sel_paths(self) -> list[str]:
        return [self.model.filePath(i) for i in self._sel_rows()]

    def _sel_changed(self):
        self._update_status()

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
    def _build_ops(self, src_paths: list[str], dest_dir: str) -> list[tuple[str, str]]:
        """Erstellt (src, dst)-Paare mit Namenskonflikt-Auflösung."""
        ops = []
        for src in src_paths:
            dst = Path(dest_dir) / Path(src).name
            if dst.exists():
                base, ext = dst.stem, dst.suffix
                i = 1
                while dst.exists():
                    dst = Path(dest_dir) / f"{base} ({i}){ext}"
                    i += 1
            ops.append((src, str(dst)))
        return ops

    def _do_copy(self, src_paths: list[str], dest_dir: str):
        ops = self._build_ops(src_paths, dest_dir)
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
        ops = self._build_ops(src_paths, dest_dir)
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
            self._trash(p)
        self.refresh()

    @staticmethod
    def _trash(path: str):
        try:
            _send2trash(path)
        except Exception:
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            except OSError:
                pass

    @staticmethod
    def _reveal_in_filemanager(path: str):
        """Datei/Ordner im nativen Dateimanager anzeigen (cross-platform)."""
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", path], capture_output=True)
            elif sys.platform == "win32":
                subprocess.run(["explorer", "/select,", path.replace("/", "\\")])
            else:
                # Linux: Ordner öffnen (xdg-open unterstützt kein --select)
                subprocess.run(["xdg-open", str(Path(path).parent)], capture_output=True)
        except Exception:
            pass

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
        if not self._clip_paths:
            return
        mode    = self._clip_mode or "copy"
        srcs    = list(self._clip_paths)
        if mode == "cut":
            self._clip_paths = []
            self._clip_mode  = None
        self._do_copy(srcs, self._cur) if mode == "copy" else self._do_move(srcs, self._cur)

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
                a_finder.triggered.connect(lambda: self._reveal_in_filemanager(paths[0]))
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
