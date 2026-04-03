"""
addressbar.py — BreadcrumbBar: klickbare Pfad-Segmente mit Textfeld-Fallback.

Standardmodus: Breadcrumb (klickbare Segmente wie Home › Dokumente › Projekte).
Wechsel zu Textfeld: Doppelklick auf Segment oder Klick auf leere Fläche.
Zurück zu Breadcrumb: Escape (ohne Navigation) oder Enter nach gültigem Pfad.
"""
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QStackedWidget,
    QPushButton, QApplication, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont


class BreadcrumbBar(QWidget):
    """Adressleiste mit klickbaren Pfad-Segmenten.

    Zeigt den aktuellen Pfad als anklickbare Segmente getrennt durch ›.
    Doppelklick wechselt in Textfeld-Modus für direkte Eingabe.

    Signals:
        path_entered(str): Wird ausgelöst wenn der Benutzer zu einem Pfad
                           navigieren möchte (Klick auf Segment oder Enter).
    """

    path_entered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path = ""

        # Tab soll die Adressleiste überspringen; Fokus nur per Klick / explizitem Aufruf
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Stacked Widget: Breadcrumb oder Textfeld ──────────────────────────
        self._stack = QStackedWidget()
        self._stack.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._stack, 1)

        # Seite 0: Breadcrumb-Ansicht
        self._crumb_widget = QWidget()
        self._crumb_layout = QHBoxLayout(self._crumb_widget)
        self._crumb_layout.setContentsMargins(4, 0, 4, 0)
        self._crumb_layout.setSpacing(0)
        self._crumb_layout.addStretch(1)  # Klick auf leere Fläche → Textfeld
        self._crumb_widget.mousePressEvent = lambda e: self._switch_to_edit()
        self._stack.addWidget(self._crumb_widget)

        # Seite 1: Textfeld
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("Pfad eingeben …")
        self._edit.returnPressed.connect(self._commit_edit)
        self._edit.installEventFilter(self)
        self._stack.addWidget(self._edit)

        self._stack.setCurrentIndex(0)

    # ── Öffentliche API ───────────────────────────────────────────────────────

    def set_path(self, path: str):
        """Setzt den angezeigten Pfad und rendert die Breadcrumbs neu."""
        self._current_path = path
        self._rebuild_crumbs(path)
        if self._stack.currentIndex() == 1:
            self._edit.setText(path)

    # ── Interne Methoden ──────────────────────────────────────────────────────

    def _rebuild_crumbs(self, path: str):
        """Löscht alle alten Segment-Buttons und baut neue auf.

        Zeigt maximal die letzten 3 Segmente; bei längerem Pfad erscheint
        ein „…"-Label als erster Eintrag.
        """
        # Alle Widgets außer dem abschließenden Stretch entfernen
        while self._crumb_layout.count() > 1:
            item = self._crumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        parts = Path(path).parts  # z. B. ('/', 'Users', 'max', 'Documents')

        # Akkumulierte Pfade für alle Segmente vorberechnen
        accumulated = []
        acc = ""
        for i, part in enumerate(parts):
            acc = part if i == 0 else str(Path(acc) / part)
            accumulated.append((part, acc))

        # Nur die letzten 3 Segmente anzeigen
        MAX_CRUMBS = 3
        visible = accumulated[-MAX_CRUMBS:]
        truncated = len(accumulated) > MAX_CRUMBS

        # „…"-Platzhalter wenn Pfad abgeschnitten wurde
        if truncated:
            ellipsis = QLabel(" … ")
            ellipsis.setStyleSheet("color: palette(mid);")
            ellipsis.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._crumb_layout.insertWidget(self._crumb_layout.count() - 1, ellipsis)
            sep = QLabel(" › ")
            sep.setStyleSheet("color: palette(mid);")
            sep.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._crumb_layout.insertWidget(self._crumb_layout.count() - 1, sep)

        for idx, (part, snap) in enumerate(visible):
            label = part if part != "/" else "⌂"
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet(
                "QPushButton { border: none; padding: 2px 4px; text-decoration: underline; }"
                "QPushButton:hover { color: palette(highlight); }"
            )
            btn.clicked.connect(lambda _, p=snap: self.path_entered.emit(p))
            btn.mouseDoubleClickEvent = lambda e: self._switch_to_edit()
            self._crumb_layout.insertWidget(self._crumb_layout.count() - 1, btn)

            # Trennzeichen › (nicht nach letztem Segment)
            if idx < len(visible) - 1:
                sep = QLabel(" › ")
                sep.setStyleSheet("color: palette(mid);")
                sep.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                self._crumb_layout.insertWidget(self._crumb_layout.count() - 1, sep)

    def _switch_to_edit(self):
        """Wechselt in Textfeld-Modus."""
        self._edit.setText(self._current_path)
        self._stack.setCurrentIndex(1)
        self._edit.setFocus()
        self._edit.selectAll()

    def _switch_to_crumbs(self):
        """Wechselt zurück in Breadcrumb-Modus."""
        self._stack.setCurrentIndex(0)

    def _commit_edit(self):
        """Enter im Textfeld: navigieren wenn Pfad existiert."""
        p = self._edit.text().strip()
        if os.path.exists(p):
            self._switch_to_crumbs()
            self.path_entered.emit(p)
        else:
            QMessageBox.warning(self, "Pfad nicht gefunden",
                                f"Der Pfad existiert nicht:\n{p}")

    def eventFilter(self, obj, event):
        """Escape im Textfeld: zurück zu Breadcrumbs ohne Navigation."""
        from PySide6.QtCore import QEvent
        if obj is self._edit and event.type() == QEvent.Type.KeyPress:
            from PySide6.QtCore import Qt
            if event.key() == Qt.Key.Key_Escape:
                self._switch_to_crumbs()
                return True
        return super().eventFilter(obj, event)

    # ── Kompatibilität mit FileBrowser (ersetzt AddressBar-API) ──────────────

    def setText(self, text: str):
        """Kompatibilitäts-Methode: wird von FileBrowser._apply() aufgerufen."""
        self.set_path(text)

    def setFocus(self, reason=None):
        # Nur bei explizitem Fokus (Tastenkürzel) in Textfeld wechseln,
        # nicht bei Tab-Navigation (TabFocusReason / BacktabFocusReason).
        from PySide6.QtCore import Qt as _Qt
        tab_reasons = {
            _Qt.FocusReason.TabFocusReason,
            _Qt.FocusReason.BacktabFocusReason,
        }
        if reason not in tab_reasons:
            self._switch_to_edit()

    def selectAll(self):
        self._edit.selectAll()

    def clearFocus(self):
        self._switch_to_crumbs()

    def hasFocus(self) -> bool:
        return self._edit.hasFocus()
