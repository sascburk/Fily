"""
models.py — FavoritesModel (QAbstractListModel) und ExplorerModel (QFileSystemModel).
"""
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import (
    Qt, QModelIndex, QAbstractListModel, QDir, QFileInfo, Signal, QSortFilterProxyModel,
    QMimeData, QUrl, QSettings,
)
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import QFileSystemModel, QFileIconProvider, QApplication, QStyle

from config import (
    CONFIG_DIR, FAV_FILE, DEFAULT_FAVORITES, ORG_NAME, SK_FAV_TRASH_REMOVED,
)


def _trash_favorite() -> dict:
    if sys.platform == "darwin":
        path = str(Path.home() / ".Trash")
    elif sys.platform == "win32":
        # Explorer-Shellziel für Papierkorb unter Windows.
        path = "shell:RecycleBinFolder"
    else:
        path = str(Path.home() / ".local" / "share" / "Trash" / "files")
    return {"name": "Papierkorb", "path": path}


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
                self._ensure_trash_favorite()
                return
            except Exception:
                pass
        self._favs = list(DEFAULT_FAVORITES)
        self._ensure_trash_favorite()

    def _move_trash_to_end(self) -> bool:
        trash_path = _trash_favorite()["path"]
        for i, fav in enumerate(self._favs):
            if fav.get("path") == trash_path:
                if i == len(self._favs) - 1:
                    return False
                item = self._favs.pop(i)
                self._favs.append(item)
                return True
        return False

    def _ensure_trash_favorite(self):
        trash = _trash_favorite()
        trash_path = trash["path"]
        settings = QSettings(ORG_NAME, "Favorites")
        trash_removed = settings.value(SK_FAV_TRASH_REMOVED, False, type=bool)
        if not trash_removed and not any(f.get("path") == trash_path for f in self._favs):
            self._favs.append(trash)
        self._move_trash_to_end()

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
            if fav.get("path") == _trash_favorite()["path"]:
                style = QApplication.style()
                if style is not None:
                    icon = style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
                    if not icon.isNull():
                        return icon
                return self._icons.icon(QFileIconProvider.IconType.Trashcan)
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
        self.layoutAboutToBeChanged.emit()
        item = self._favs.pop(src)
        if src < dst:
            dst -= 1
        self._favs.insert(dst, item)
        self._move_trash_to_end()
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
        self.layoutAboutToBeChanged.emit()
        self._favs.append({"name": name, "path": path})
        self._move_trash_to_end()
        self.layoutChanged.emit()
        if path == _trash_favorite()["path"]:
            QSettings(ORG_NAME, "Favorites").setValue(SK_FAV_TRASH_REMOVED, False)
        self.save()

    def remove(self, row: int):
        if 0 <= row < len(self._favs):
            removed_path = self._favs[row].get("path")
            self.beginRemoveRows(QModelIndex(), row, row)
            self._favs.pop(row)
            self.endRemoveRows()
            if removed_path == _trash_favorite()["path"]:
                QSettings(ORG_NAME, "Favorites").setValue(SK_FAV_TRASH_REMOVED, True)
            self.save()

    def path_at(self, row: int) -> str | None:
        return self._favs[row]["path"] if 0 <= row < len(self._favs) else None


class ExplorerModel(QFileSystemModel):
    HEADERS = ["Name", "Änderungsdatum", "Größe", "Art"]
    # Interne QFileSystemModel-Spalten in dieser Runtime:
    # 0=Name, 1=Größe, 2=Datum, 3=Art
    _SORT_COLUMN_MAP = {1: 2, 2: 1, 3: 3}

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

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder):
        """Mappt sichtbare Spalten auf QFileSystemModel-interne Sortierspalten."""
        internal_column = self._SORT_COLUMN_MAP.get(column, column)
        super().sort(internal_column, order)

    def _is_hidden_entry(self, index: QModelIndex) -> bool:
        i0 = self.sibling(index.row(), 0, index)
        fi = self.fileInfo(i0)
        name = fi.fileName()
        # '.' und '..' ebenfalls als versteckte Unix-Einträge behandeln.
        return fi.isHidden() or name in (".", "..")

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        col = index.column()

        if role == Qt.ForegroundRole and self._is_hidden_entry(index):
            c = QColor(Qt.GlobalColor.gray)
            c.setAlpha(140)
            return QBrush(c)

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


class ExplorerProxyModel(QSortFilterProxyModel):
    """Proxy für benutzerdefinierte Sortierung (u. a. Art nach Dateiendung)."""

    directoryLoaded = Signal(str)

    def __init__(self, source: ExplorerModel, parent=None):
        super().__init__(parent)
        self.setSourceModel(source)
        self.setDynamicSortFilter(True)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._folders_always_top = True
        source.directoryLoaded.connect(self.directoryLoaded.emit)

    def set_folders_always_top(self, enabled: bool):
        self._folders_always_top = bool(enabled)
        self.invalidate()

    def folders_always_top(self) -> bool:
        return self._folders_always_top

    def source_model(self) -> ExplorerModel:
        src = self.sourceModel()
        return src  # type: ignore[return-value]

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        src = self.source_model()
        # Qt übergibt hier bereits SOURCE-Indizes (nicht Proxy-Indizes).
        l0 = src.fileInfo(left.siblingAtColumn(0))
        r0 = src.fileInfo(right.siblingAtColumn(0))
        col = left.column()

        if l0.isDir() != r0.isDir():
            # Ordner als Gruppe behandeln (nicht zwischen Dateien mischen).
            # Optional: immer oben, unabhängig von Sortierreihenfolge.
            if self._folders_always_top and self.sortOrder() == Qt.SortOrder.DescendingOrder:
                return not l0.isDir()
            return l0.isDir()

        if col == 3:
            # Art: nach Dateiendung sortieren, Ordner als "ordner" gruppieren.
            l_key = ("ordner", l0.fileName().lower()) if l0.isDir() else (l0.suffix().lower(), l0.fileName().lower())
            r_key = ("ordner", r0.fileName().lower()) if r0.isDir() else (r0.suffix().lower(), r0.fileName().lower())
            return l_key < r_key

        if col == 2:
            l_size = -1 if l0.isDir() else l0.size()
            r_size = -1 if r0.isDir() else r0.size()
            if l_size != r_size:
                return l_size < r_size
            return l0.fileName().lower() < r0.fileName().lower()

        if col == 1:
            l_dt = l0.lastModified()
            r_dt = r0.lastModified()
            if l_dt != r_dt:
                return l_dt < r_dt
            return l0.fileName().lower() < r0.fileName().lower()

        return super().lessThan(left, right)

    # Delegate-Methoden, damit der bestehende Browser-Code weiter funktioniert.
    def setRootPath(self, path: str):
        return self.source_model().setRootPath(path)

    def filePath(self, index: QModelIndex) -> str:
        src = self.source_model()
        if index.model() is src:
            return src.filePath(index)
        return src.filePath(self.mapToSource(index))

    def fileInfo(self, index: QModelIndex) -> QFileInfo:
        src = self.source_model()
        if index.model() is src:
            return src.fileInfo(index)
        return src.fileInfo(self.mapToSource(index))

    def index(self, *args):
        if len(args) == 1 and isinstance(args[0], str):
            return self.mapFromSource(self.source_model().index(args[0]))
        return super().index(*args)

    def setFilter(self, filters):
        return self.source_model().setFilter(filters)

    def filter(self):
        return self.source_model().filter()

    def setNameFilters(self, filters):
        return self.source_model().setNameFilters(filters)

    def setNameFilterDisables(self, b: bool):
        return self.source_model().setNameFilterDisables(b)
