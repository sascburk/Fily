"""
addressbar.py — AddressBar: einfaches Pfad-Textfeld.

Wird in einem späteren Task durch BreadcrumbBar erweitert (Feature F2).
Bis dahin: QLineEdit mit Enter-Navigation und Escape-Abbruch.
"""
import os

from PySide6.QtWidgets import QLineEdit, QMessageBox
from PySide6.QtCore import Qt, Signal


class AddressBar(QLineEdit):
    """Adressleiste mit Enter-Navigation und Escape-Abbruch.

    Signal path_entered(str): Wird ausgelöst wenn Benutzer Enter drückt und
    der eingegebene Pfad existiert.
    """

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
