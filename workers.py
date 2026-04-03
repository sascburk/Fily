#!/usr/bin/env python3
"""
workers.py — UndoStack und CopyWorker für Hintergrundoperationen.
"""

import shutil
from pathlib import Path

from PySide6.QtCore import QThread, Signal


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
