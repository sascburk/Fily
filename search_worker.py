"""
search_worker.py — SearchWorker: rekursive Dateisuche in einem QThread.
"""
from pathlib import Path
from PySide6.QtCore import QThread, Signal


class SearchWorker(QThread):
    """Sucht rekursiv nach Dateien/Ordnern, deren Name den Suchbegriff enthält.

    Signals:
        result(str):    Pfad einer gefundenen Datei/Ordner
        finished():     Suche abgeschlossen
    """

    result   = Signal(str)
    finished = Signal()

    def __init__(self, root: str, term: str, parent=None):
        super().__init__(parent)
        self._root = root
        self._term = term.lower()

    def run(self):
        try:
            for entry in Path(self._root).rglob("*"):
                if self.isInterruptionRequested():
                    break
                if self._term in entry.name.lower():
                    self.result.emit(str(entry))
        except PermissionError:
            pass
        self.finished.emit()
