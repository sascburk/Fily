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


# ──────────────────────────────────────────────────────────────────────────────
# Undo-Stack
# ──────────────────────────────────────────────────────────────────────────────
class UndoStack:
    """Einfacher Undo-Stack für Dateioperationen (Umbenennen, Ordner, Kopieren, Verschieben)."""

    MAX = 50

    def __init__(self):
        self._stack: list[dict] = []

    def push(self, entry: dict):
        self._stack.append(entry)
        if len(self._stack) > self.MAX:
            self._stack.pop(0)

    def pop(self) -> dict | None:
        return self._stack.pop() if self._stack else None

    def can_undo(self) -> bool:
        return bool(self._stack)

    def peek_description(self) -> str:
        if not self._stack:
            return ""
        e = self._stack[-1]
        op = e.get("op", "")
        if op == "rename":
            return f"Umbenennen von '{Path(e['old']).name}'"
        if op == "batch_rename":
            return f"{len(e['pairs'])} Elemente umbenennen"
        if op == "mkdir":
            return f"Ordner '{Path(e['path']).name}' erstellen"
        if op == "move":
            return f"Verschieben ({len(e['pairs'])} Element(e))"
        if op == "copy":
            return f"Kopieren ({len(e['paths'])} Element(e))"
        return op


# ──────────────────────────────────────────────────────────────────────────────
# Hintergrund-Kopier-Worker
# ──────────────────────────────────────────────────────────────────────────────
class CopyWorker(QThread):
    """Kopier-/Verschiebe-Operationen in einem Hintergrundthread."""

    progress     = Signal(int, int)   # aktuell, gesamt
    error        = Signal(str)
    finished_ops = Signal(list)       # Liste der Ziel-Pfade

    def __init__(self, operations: list[tuple[str, str]], mode: str, parent=None):
        super().__init__(parent)
        self._ops  = operations   # [(src, dst), ...]
        self._mode = mode         # 'copy' | 'move'

    def run(self):
        dst_paths = []
        total = len(self._ops)
        for i, (src, dst) in enumerate(self._ops):
            if self.isInterruptionRequested():
                break
            self.progress.emit(i, total)
            try:
                src_p = Path(src)
                if self._mode == "copy":
                    (shutil.copytree if src_p.is_dir() else shutil.copy2)(src, dst)
                else:
                    shutil.move(src, dst)
                dst_paths.append(dst)
            except OSError as e:
                self.error.emit(str(e))
        self.progress.emit(total, total)
        self.finished_ops.emit(dst_paths)


# ──────────────────────────────────────────────────────────────────────────────
# Batch-Umbenennen-Dialog
# ──────────────────────────────────────────────────────────────────────────────
class BatchRenameDialog(QDialog):
    """Dialog zum Umbenennen mehrerer Dateien nach einem Muster."""

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mehrfach umbenennen")
        self.setMinimumSize(620, 420)
        self._paths = paths

        layout = QVBoxLayout(self)

        hint = QLabel(
            "Platzhalter: <b>{name}</b> = Originalname ohne Erweiterung, "
            "<b>{n}</b> = laufende Nummer, <b>{ext}</b> = Erweiterung (mit Punkt)"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        pattern_row = QHBoxLayout()
        pattern_row.addWidget(QLabel("Muster:"))
        self._pattern = QLineEdit()
        self._pattern.setPlaceholderText("z. B.  Urlaub_{n:03d}{ext}  oder  {name}_neu{ext}")
        self._pattern.textChanged.connect(self._update_preview)
        pattern_row.addWidget(self._pattern, 1)
        layout.addLayout(pattern_row)

        self._table = QTableWidget(len(paths), 2)
        self._table.setHorizontalHeaderLabels(["Vorher", "Nachher"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for i, p in enumerate(paths):
            self._table.setItem(i, 0, QTableWidgetItem(Path(p).name))
            self._table.setItem(i, 1, QTableWidgetItem(Path(p).name))
        layout.addWidget(self._table, 1)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _update_preview(self, pattern: str):
        for i, p in enumerate(self._paths):
            name = Path(p).stem
            ext  = Path(p).suffix
            if pattern:
                try:
                    new_name = pattern.format(name=name, n=i + 1, ext=ext)
                except (KeyError, ValueError, IndexError):
                    new_name = "— Ungültiges Muster —"
            else:
                new_name = Path(p).name
            item = self._table.item(i, 1)
            if item:
                item.setText(new_name)

    def renamed_pairs(self) -> list[tuple[str, str]]:
        """Gibt [(alter_pfad, neuer_name), ...] zurück (nur geänderte)."""
        result = []
        for i, p in enumerate(self._paths):
            item = self._table.item(i, 1)
            new_name = item.text() if item else ""
            if new_name and new_name != "— Ungültiges Muster —" and new_name != Path(p).name:
                result.append((p, new_name))
        return result


# ──────────────────────────────────────────────────────────────────────────────
# Favoriten-Modell
# ──────────────────────────────────────────────────────────────────────────────
class FavoritesModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._favs: list[dict] = []
        self._icons = QFileIconProvider()
        self.load()

    def load(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if FAV_FILE.exists():
            try:
                with open(FAV_FILE, encoding="utf-8") as f:
                    self._favs = json.load(f)
                return
            except Exception:
                pass
        self._favs = list(DEFAULT_FAVORITES)

    def save(self):
        try:
            with open(FAV_FILE, "w", encoding="utf-8") as f:
                json.dump(self._favs, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._favs)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._favs):
            return None
        fav = self._favs[index.row()]
        if role == Qt.DisplayRole:
            return fav["name"]
        if role == Qt.DecorationRole:
            fi = QFileInfo(fav["path"])
            return self._icons.icon(fi) if fi.exists() else self._icons.icon(QFileIconProvider.IconType.Folder)
        if role == Qt.ToolTipRole:
            return fav["path"]
        if role == Qt.UserRole:
            return fav["path"]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.isValid():
            return base | Qt.ItemIsEditable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        return base | Qt.ItemIsDropEnabled

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.MoveAction

    def mimeTypes(self) -> list[str]:
        return ["application/x-fav-row"]

    def mimeData(self, indexes) -> QMimeData:
        md = QMimeData()
        if indexes:
            md.setData("application/x-fav-row", str(indexes[0].row()).encode())
        return md

    def dropMimeData(self, data: QMimeData, action, row, col, parent) -> bool:
        if not data.hasFormat("application/x-fav-row"):
            return False
        src = int(data.data("application/x-fav-row").data())
        dst = row if row >= 0 else self.rowCount()
        if src == dst or src == dst - 1:
            return False
        item = self._favs.pop(src)
        if src < dst:
            dst -= 1
        self._favs.insert(dst, item)
        self.layoutChanged.emit()
        self.save()
        return True

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:
        if role == Qt.EditRole and index.isValid():
            self._favs[index.row()]["name"] = value
            self.dataChanged.emit(index, index, [role])
            self.save()
            return True
        return False

    def add(self, name: str, path: str):
        for fav in self._favs:
            if fav["path"] == path:
                return
        r = self.rowCount()
        self.beginInsertRows(QModelIndex(), r, r)
        self._favs.append({"name": name, "path": path})
        self.endInsertRows()
        self.save()

    def remove(self, row: int):
        if 0 <= row < len(self._favs):
            self.beginRemoveRows(QModelIndex(), row, row)
            self._favs.pop(row)
            self.endRemoveRows()
            self.save()

    def path_at(self, row: int) -> str | None:
        return self._favs[row]["path"] if 0 <= row < len(self._favs) else None


# ──────────────────────────────────────────────────────────────────────────────
# Favoriten-Panel (linke Seitenleiste) — mit Liquid-Glass-Effekt
# ──────────────────────────────────────────────────────────────────────────────
class FavoritesPanel(QWidget):
    navigate = Signal(str)
    add_fav  = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(150)
        self.setMaximumWidth(300)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = QLabel("  Favoriten")
        self._header.setFixedHeight(34)
        hf = self._header.font()
        if hf.pointSize() > 0:
            hf.setPointSize(11)
        hf.setBold(True)
        self._header.setFont(hf)
        self._header.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout.addWidget(self._header)

        self.view = QListView()
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setStyleSheet(
            "QListView { background: transparent; border: none; }"
            "QListView::item:selected:active  { background: palette(highlight); color: palette(highlighted-text); }"
            "QListView::item:selected:!active { background: palette(mid); color: palette(text); }"
        )
        self.view.setSpacing(2)
        self.view.setIconSize(QSize(22, 22))
        vf = self.view.font()
        if vf.pointSize() > 0:
            vf.setPointSize(13)
        self.view.setFont(vf)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setDragEnabled(True)
        self.view.setAcceptDrops(True)
        self.view.setDefaultDropAction(Qt.MoveAction)
        self.view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.view.setDropIndicatorShown(True)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._ctx_menu)
        self.view.clicked.connect(self._clicked)
        self.view.installEventFilter(self)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.model = FavoritesModel()
        self.view.setModel(self.model)
        layout.addWidget(self.view, 1)

        self.btn_add = QToolButton()
        self.btn_add.setText("＋  Ordner hinzufügen")
        self.btn_add.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.btn_add.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_add.setFixedHeight(30)
        self.btn_add.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_add.setStyleSheet("QToolButton { background: transparent; border: none; font-size: 12px; }")
        self.btn_add.clicked.connect(self._add_dialog)
        layout.addWidget(self.btn_add)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        r = self.rect()

        bg   = self.palette().color(QPalette.ColorRole.Window)
        dark = bg.lightness() < 128

        if dark:
            base_top = QColor(52,  56,  68,  230)
            base_bot = QColor(38,  41,  52,  240)
            specular = QColor(120, 140, 180,  45)
            border_c = QColor(90,  100, 130, 130)
            tint     = QColor(80,  100, 160,  18)
        else:
            base_top = QColor(232, 236, 245, 210)
            base_bot = QColor(215, 220, 235, 220)
            specular = QColor(255, 255, 255, 160)
            border_c = QColor(180, 190, 215, 140)
            tint     = QColor(180, 200, 255,  22)

        grad = QLinearGradient(0, 0, 0, r.height())
        grad.setColorAt(0.0, base_top)
        grad.setColorAt(1.0, base_bot)
        painter.fillRect(r, QBrush(grad))

        tint_grad = QLinearGradient(0, 0, r.width(), 0)
        tint_grad.setColorAt(0.0, tint)
        tint_grad.setColorAt(1.0, QColor(tint.red(), tint.green(), tint.blue(), 0))
        painter.fillRect(r, QBrush(tint_grad))

        spec_h = min(50, r.height() // 3)
        spec_grad = QLinearGradient(0, 0, 0, spec_h)
        spec_grad.setColorAt(0.0, specular)
        spec_grad.setColorAt(1.0, QColor(specular.red(), specular.green(), specular.blue(), 0))
        painter.fillRect(0, 0, r.width(), spec_h, QBrush(spec_grad))

        painter.setPen(QPen(border_c, 1))
        painter.drawLine(r.width() - 1, 0, r.width() - 1, r.height())
        painter.drawLine(0, r.height() - 1, r.width() - 1, r.height() - 1)

    def eventFilter(self, obj, event):
        if obj is self.view:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._clicked(self.view.currentIndex())
                    return True
            elif event.type() == QEvent.Type.FocusIn:
                if not self.view.selectionModel().hasSelection():
                    first = self.model.index(0)
                    if first.isValid():
                        self.view.setCurrentIndex(first)
                        self.view.selectionModel().select(
                            first, QItemSelectionModel.SelectionFlag.ClearAndSelect
                        )
        return super().eventFilter(obj, event)

    def _clicked(self, index: QModelIndex):
        path = self.model.path_at(index.row())
        if path and os.path.isdir(path):
            self.navigate.emit(path)

    def _ctx_menu(self, pos):
        index = self.view.indexAt(pos)
        menu = QMenu(self)
        rename_action = remove_action = None
        if index.isValid():
            rename_action = menu.addAction("Umbenennen")
            remove_action = menu.addAction("Aus Favoriten entfernen")
            menu.addSeparator()
        add_action = menu.addAction("Ordner hinzufügen …")

        action = menu.exec(self.view.viewport().mapToGlobal(pos))
        if not action:
            return
        if index.isValid():
            if action == rename_action:
                old_name = self.model.data(index, Qt.ItemDataRole.DisplayRole)
                new_name, ok = QInputDialog.getText(
                    self, "Favorit umbenennen", "Neuer Name:", text=old_name
                )
                if ok and new_name:
                    self.model.setData(index, new_name, Qt.ItemDataRole.EditRole)
            elif action == remove_action:
                self.model.remove(index.row())
        if action == add_action:
            self._add_dialog()

    def _add_dialog(self):
        opts = QFileDialog.Option.DontUseNativeDialog if sys.platform.startswith("linux") else QFileDialog.Option(0)
        path = QFileDialog.getExistingDirectory(
            self, "Ordner zu Favoriten hinzufügen", str(Path.home()), opts
        )
        if path:
            self.model.add(Path(path).name or path, path)

    def add_current(self, path: str):
        if path and os.path.isdir(path):
            self.model.add(Path(path).name or path, path)

    def highlight_path(self, path: str):
        for row in range(self.model.rowCount()):
            if self.model.path_at(row) == path:
                self.view.setCurrentIndex(self.model.index(row))
                return
        self.view.clearSelection()


# ──────────────────────────────────────────────────────────────────────────────
# Erweitertes Dateisystem-Modell  (Name | Änderungsdatum | Größe | Art)
# ──────────────────────────────────────────────────────────────────────────────
class ExplorerModel(QFileSystemModel):
    HEADERS = ["Name", "Änderungsdatum", "Größe", "Art"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)
        self.setRootPath("")

    def columnCount(self, parent=QModelIndex()) -> int:
        return 4

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        col = index.column()

        if col == 0:
            return super().data(index, role)

        if col == 1:
            if role == Qt.DisplayRole:
                fi = self.fileInfo(self.sibling(index.row(), 0, index))
                return fi.lastModified().toString("dd.MM.yyyy  HH:mm")
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            return None

        if col == 2:
            if role == Qt.DisplayRole:
                fi = self.fileInfo(self.sibling(index.row(), 0, index))
                return "" if fi.isDir() else self._fmt_size(fi.size())
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            return None

        if col == 3:
            if role == Qt.DisplayRole:
                fi = self.fileInfo(self.sibling(index.row(), 0, index))
                if fi.isDir():
                    return "Ordner"
                suf = fi.suffix().upper()
                return f"{suf}-Datei" if suf else "Datei"
            return None

        return None

    @staticmethod
    def _fmt_size(n: int) -> str:
        if n < 1024:
            return f"{n} B"
        for unit in ("KB", "MB", "GB", "TB"):
            n /= 1024
            if n < 1024 or unit == "TB":
                return f"{n:.1f} {unit}"
        return f"{n:.1f} TB"


# ──────────────────────────────────────────────────────────────────────────────
# ExplorerTreeView — QTreeView mit echtem Drag&Drop in Unterordner
# ──────────────────────────────────────────────────────────────────────────────
class ExplorerTreeView(QTreeView):
    """Erweiterter QTreeView: Dateien per Drag&Drop in Unterordner verschieben/kopieren."""

    files_dropped = Signal(list, str, Qt.DropAction)   # [src_paths], dest_dir, action

    _SEL = QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows

    def __init__(self, parent=None):
        super().__init__(parent)
        # Selektionsfarbe bleibt blau — auch wenn der Fokus woanders ist
        self.setStyleSheet(
            "QTreeView::item:selected:active  { background: palette(highlight); color: palette(highlighted-text); }"
            "QTreeView::item:selected:!active { background: palette(mid); color: palette(text); }"
        )

    def _select(self, idx):
        """Setzt Cursor UND visuelle Selektion (blau) auf idx."""
        self.setCurrentIndex(idx)
        self.selectionModel().select(idx, self._SEL)
        self.scrollTo(idx)

    def focusInEvent(self, e):
        should_select = not self.selectionModel().hasSelection()
        super().focusInEvent(e)
        if should_select:
            first = self.model().index(0, 0, self.rootIndex())
            if first.isValid():
                self._select(first)

    def keyPressEvent(self, e):
        has_sel = self.selectionModel().hasSelection()
        if e.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            step  = -1 if e.key() == Qt.Key.Key_Backtab else 1
            root  = self.rootIndex()
            count = self.model().rowCount(root)
            if count:
                row = (self.currentIndex().row() + step) % count if has_sel else 0
                self._select(self.model().index(row, 0, root))
            e.accept()
        elif e.key() == Qt.Key.Key_Down and not has_sel:
            first = self.model().index(0, 0, self.rootIndex())
            if first.isValid():
                self._select(first)
            e.accept()
        elif e.key() == Qt.Key.Key_Up and not has_sel:
            root  = self.rootIndex()
            count = self.model().rowCount(root)
            if count:
                self._select(self.model().index(count - 1, 0, root))
            e.accept()
        else:
            super().keyPressEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            idx = self.indexAt(e.position().toPoint())
            if idx.isValid():
                path = self.model().filePath(idx)
                if os.path.isdir(path):
                    self.setCurrentIndex(idx)
                    e.acceptProposedAction()
                    return
            e.ignore()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            idx = self.indexAt(e.position().toPoint())
            if idx.isValid():
                dest = self.model().filePath(idx)
                if os.path.isdir(dest):
                    paths = [u.toLocalFile() for u in e.mimeData().urls()]
                    self.files_dropped.emit(paths, dest, e.dropAction())
                    e.acceptProposedAction()
                    return
            e.ignore()
        else:
            super().dropEvent(e)


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
# Tastaturkürzel-Dialog
# ──────────────────────────────────────────────────────────────────────────────
def _shortcut_table() -> list[tuple[str, str]]:
    """Gibt plattformspezifische Tastaturkürzel zurück."""
    is_mac = sys.platform == "darwin"
    cmd    = "Cmd" if is_mac else "Ctrl"
    delete = "Cmd+Backspace" if is_mac else "Delete"

    tab_next = "Cmd+Shift+→" if is_mac else "Ctrl+Tab"
    tab_prev = "Cmd+Shift+←" if is_mac else "Ctrl+Shift+Tab"

    return [
        ("Navigation", ""),
        ("Ordner öffnen",            "Enter / Doppelklick"),
        ("Zurück",                   "Alt+←"),
        ("Vor",                      "Alt+→"),
        ("Übergeordneter Ordner",    f"Alt+↑  /  Backspace"),
        ("Adressleiste fokussieren", f"{cmd}+L  /  F4"),
        ("Suche fokussieren",        f"{cmd}+F"),
        ("", ""),
        ("Tabs", ""),
        ("Neuer Tab",                f"{cmd}+T"),
        ("Tab schließen",            f"{cmd}+W"),
        ("Nächster Tab",             tab_next),
        ("Vorheriger Tab",           tab_prev),
        ("", ""),
        ("Ansicht", ""),
        ("Aktualisieren",            "F5"),
        ("Versteckte Dateien",       "Rechtsklick → Menü"),
        ("", ""),
        ("Auswahl", ""),
        ("Alle auswählen",           f"{cmd}+A"),
        ("Nächstes Element",         "Tab"),
        ("Vorheriges Element",       "Shift+Tab"),
        ("", ""),
        ("Bearbeiten", ""),
        ("Kopieren",                 f"{cmd}+C"),
        ("Ausschneiden",             f"{cmd}+X"),
        ("Einfügen",                 f"{cmd}+V"),
        ("Umbenennen",               "F2"),
        ("In Papierkorb",            delete),
        ("Rückgängig",               f"{cmd}+Z"),
        ("Neuer Ordner",             f"{cmd}+N"),
        ("", ""),
        ("Sonstiges", ""),
        ("Beenden",                  f"{cmd}+Q"),
    ]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tastaturkürzel")
        self.setMinimumWidth(420)
        self.setMinimumHeight(640)
        layout = QVBoxLayout(self)

        table = QTableWidget(self)
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Aktion", "Kürzel"])
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)

        rows = _shortcut_table()
        table.setRowCount(len(rows))
        for i, (action, shortcut) in enumerate(rows):
            if action == "" and shortcut == "":
                # Leerzeile
                table.setRowHeight(i, 6)
                table.setItem(i, 0, QTableWidgetItem(""))
                table.setItem(i, 1, QTableWidgetItem(""))
            elif shortcut == "":
                # Kategorie-Überschrift
                item = QTableWidgetItem(f"  {action}")
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                table.setItem(i, 0, item)
                table.setItem(i, 1, QTableWidgetItem(""))
                table.setRowHeight(i, 22)
            else:
                table.setItem(i, 0, QTableWidgetItem(f"    {action}"))
                sc_item = QTableWidgetItem(shortcut)
                sc_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(i, 1, sc_item)

        layout.addWidget(table)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btns.accepted.connect(self.accept)
        layout.addWidget(btns)


# ──────────────────────────────────────────────────────────────────────────────
# Über-Dialog
# ──────────────────────────────────────────────────────────────────────────────
class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Über {APP_NAME}")
        self.setFixedWidth(380)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel(f"<b style='font-size:18px'>{APP_NAME}</b>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        version = QLabel("Version 1.3.0")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(version)

        desc = QLabel("Ein schneller, übersichtlicher Dateiexplorer\nfür macOS, Linux und Windows.")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(4)

        github_btn = QPushButton("  GitHub — Quellcode")
        github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        github_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        layout.addWidget(github_btn)

        coffee_btn = QPushButton("☕  Buy me a coffee")
        coffee_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        coffee_btn.setStyleSheet("background-color: #FFDD00; color: #000; font-weight: bold;")
        coffee_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(BUYMEACOFFEE_URL)))
        layout.addWidget(coffee_btn)

        layout.addSpacing(4)

        license_lbl = QLabel('Lizenz: <a href="https://opensource.org/licenses/MIT">MIT</a>')
        license_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        license_lbl.setOpenExternalLinks(True)
        license_lbl.setStyleSheet("font-size: 11px; color: gray;")
        layout.addWidget(license_lbl)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btns.accepted.connect(self.accept)
        layout.addWidget(btns)


# ──────────────────────────────────────────────────────────────────────────────
# App-weiter Event-Filter für Tab-Wechsel (macOS: Cmd+Shift+←/→)
# Auf Windows/Linux wird Ctrl+Tab direkt als WindowShortcut registriert.
# ──────────────────────────────────────────────────────────────────────────────
class _CtrlTabFilter(QObject):
    """Fängt Cmd+Shift+←/→ auf macOS ab (System schluckt Ctrl+Tab)."""

    def __init__(self, window):
        super().__init__()
        self._win = window

    def eventFilter(self, obj, event):
        if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride):
            return False
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit):
            return False
        mod = event.modifiers()
        key = event.key()
        # Nur macOS: Cmd+Shift+← / Cmd+Shift+→
        cmd_shift = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        if mod == cmd_shift and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            if event.type() == QEvent.Type.KeyPress:
                if key == Qt.Key.Key_Left:
                    self._win._prev_tab()
                else:
                    self._win._next_tab()
            return True  # ShortcutOverride ebenfalls konsumieren
        return False


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
