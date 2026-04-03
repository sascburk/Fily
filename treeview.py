"""
treeview.py — ExplorerTreeView: QTreeView mit Drag&Drop-Erweiterungen.
"""
import os

from PySide6.QtCore import Qt, QModelIndex, Signal
from PySide6.QtWidgets import QTreeView
from PySide6.QtCore import QItemSelectionModel


class ExplorerTreeView(QTreeView):
    """QTreeView mit echtem Drag&Drop in Unterordner und aus der App heraus.

    Emittiert files_dropped(paths, dest_dir, action) wenn Dateien per
    Drag&Drop auf einen Ordner oder die leere Fläche fallen gelassen werden.
    Bug B1 Fix: Wenn kein Unterordner unter dem Cursor liegt, wird der
    aktuelle Ordner (_current_path) als Ziel verwendet.
    """

    # Wird von FileBrowser verbunden
    files_dropped = Signal(list, str, Qt.DropAction)

    _SEL = QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows

    def __init__(self, parent=None):
        super().__init__(parent)
        # Selektionsfarbe bleibt blau auch wenn Fokus woanders ist
        self.setStyleSheet(
            "QTreeView::item:selected:active  { background: palette(highlight); color: palette(highlighted-text); }"
            "QTreeView::item:selected:!active { background: palette(mid); color: palette(text); }"
        )
        # Wird von FileBrowser gesetzt, bevor Drops verarbeitet werden
        self._current_path: str = ""

    def _select(self, idx: QModelIndex):
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
        elif e.key() == Qt.Key.Key_Down:
            root  = self.rootIndex()
            count = self.model().rowCount(root)
            if not has_sel:
                if count:
                    self._select(self.model().index(0, 0, root))
                e.accept()
            elif count and self.currentIndex().row() >= count - 1:
                self._select(self.model().index(0, 0, root))
                e.accept()
            else:
                super().keyPressEvent(e)
        elif e.key() == Qt.Key.Key_Up:
            root  = self.rootIndex()
            count = self.model().rowCount(root)
            if not has_sel:
                if count:
                    self._select(self.model().index(count - 1, 0, root))
                e.accept()
            elif count and self.currentIndex().row() <= 0:
                self._select(self.model().index(count - 1, 0, root))
                e.accept()
            else:
                super().keyPressEvent(e)
        else:
            super().keyPressEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        """Akzeptiert Drops auf Unterordner ODER auf die leere Fläche (= aktueller Ordner).

        Bug B1: Früher wurde e.ignore() aufgerufen wenn kein Verzeichnis unter
        dem Cursor lag — Drop auf leere Fläche war damit unmöglich.
        Fix: Auch leere Fläche akzeptieren; dropEvent entscheidet dann den Zielordner.
        """
        if e.mimeData().hasUrls():
            idx = self.indexAt(e.position().toPoint())
            if idx.isValid():
                path = self.model().filePath(idx)
                if os.path.isdir(path):
                    self.setCurrentIndex(idx)
                    e.acceptProposedAction()
                    return
            # Kein Unterordner unter Cursor — trotzdem akzeptieren (aktueller Ordner)
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        """Verarbeitet den Drop.

        Ziel ist der Unterordner unter dem Cursor, oder — falls keiner da ist —
        der aktuelle Ordner (_current_path, der von FileBrowser gesetzt wird).
        """
        if e.mimeData().hasUrls():
            idx = self.indexAt(e.position().toPoint())
            if idx.isValid():
                dest = self.model().filePath(idx)
                if os.path.isdir(dest):
                    paths = [u.toLocalFile() for u in e.mimeData().urls()]
                    self.files_dropped.emit(paths, dest, e.dropAction())
                    e.acceptProposedAction()
                    return
            # Leere Fläche: aktuellen Ordner als Ziel verwenden
            if self._current_path:
                paths = [u.toLocalFile() for u in e.mimeData().urls()]
                self.files_dropped.emit(paths, self._current_path, e.dropAction())
                e.acceptProposedAction()
            else:
                e.ignore()
        else:
            super().dropEvent(e)
