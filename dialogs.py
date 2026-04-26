"""
dialogs.py — Alle modalen Dialoge und der macOS-Tab-Event-Filter.

Klassen:
    BatchRenameDialog  — Mehrfach-Umbenennen mit Muster-Vorschau
    ShortcutsDialog    — Tastaturkürzel-Tabelle
    AboutDialog        — Über-Dialog mit Links
    _CtrlTabFilter     — macOS: Cmd+Shift+←/→ als Tab-Navigation
"""
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QDialogButtonBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QPushButton, QApplication,
)
from PySide6.QtCore import Qt, QEvent, QObject, QModelIndex, QUrl
from PySide6.QtGui import QDesktopServices

from config import APP_NAME, VERSION, BUYMEACOFFEE_URL, GITHUB_URL


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
def _shortcut_table() -> list[tuple[str, str]]:
    """Gibt plattformspezifische Tastaturkürzel zurück."""
    is_mac = sys.platform == "darwin"
    cmd    = "Cmd" if is_mac else "Ctrl"
    delete = "Cmd+Backspace" if is_mac else "Delete / Ctrl+Backspace"
    hidden = "Cmd+Shift+." if is_mac else "Ctrl+Shift+H"

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
        ("Split-Pane",               "F8"),
        ("Vorschau",                 "F9 / Space"),
        ("", ""),
        ("Ansicht", ""),
        ("Aktualisieren",            "F5"),
        ("Versteckte Dateien",       hidden),
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
        ("Neue Datei",               f"{cmd}+Shift+N"),
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

        version = QLabel(f"Version {VERSION}")
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
