"""
toolbar.py — Moderne Browser-Toolbar mit SVG-Icons (Fallback: Qt-Standard-Icons).

Schaltflächen: Zurück | Vor | Hoch | Aktualisieren | Neuer Ordner | Ansicht wechseln.
Die Toolbar ist kompakt (28×28 px Icons) und hat keine Text-Labels.
"""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QToolButton, QSizePolicy, QApplication, QStyle
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon


class BrowserToolbar(QWidget):
    """Kompakte Toolbar für den FileBrowser.

    Signals:
        back_clicked: Zurück-Button gedrückt
        forward_clicked: Vor-Button gedrückt
        up_clicked: Hoch-Button gedrückt
        reload_clicked: Aktualisieren-Button gedrückt
        new_folder_clicked: Neuer-Ordner-Button gedrückt
        view_toggle: Ansicht-Wechsel-Button gedrückt (Liste ↔ Icon)
    """

    back_clicked       = Signal()
    forward_clicked    = Signal()
    up_clicked         = Signal()
    reload_clicked     = Signal()
    new_folder_clicked = Signal()
    view_toggle        = Signal()   # Liste ↔ Icon-Raster

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(4)

        self.btn_back    = self._btn("Zurück (Alt+←)",       QStyle.StandardPixmap.SP_ArrowBack)
        self.btn_forward = self._btn("Vor (Alt+→)",           QStyle.StandardPixmap.SP_ArrowForward)
        self.btn_up      = self._btn("Übergeordnet (Alt+↑)",  QStyle.StandardPixmap.SP_ArrowUp)
        self.btn_reload  = self._btn("Aktualisieren (F5)",    QStyle.StandardPixmap.SP_BrowserReload)
        self.btn_new_dir = self._btn("Neuer Ordner (Ctrl+N)", QStyle.StandardPixmap.SP_FileDialogNewFolder)
        self.btn_view    = self._btn("Ansicht wechseln",      QStyle.StandardPixmap.SP_FileDialogDetailedView)

        # Zurück/Vor zu Beginn deaktiviert (keine Navigationhistorie vorhanden)
        self.btn_back.setEnabled(False)
        self.btn_forward.setEnabled(False)

        self.btn_back.clicked.connect(self.back_clicked)
        self.btn_forward.clicked.connect(self.forward_clicked)
        self.btn_up.clicked.connect(self.up_clicked)
        self.btn_reload.clicked.connect(self.reload_clicked)
        self.btn_new_dir.clicked.connect(self.new_folder_clicked)
        self.btn_view.clicked.connect(self.view_toggle)

        for btn in (self.btn_back, self.btn_forward, self.btn_up,
                    self.btn_reload, self.btn_new_dir, self.btn_view):
            layout.addWidget(btn)

        layout.addStretch(1)

    def _btn(self, tip: str, std_icon) -> QToolButton:
        """Erstellt einen kompakten Icon-Button mit Qt-Standard-Icon."""
        btn = QToolButton()
        btn.setToolTip(tip)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setFixedSize(28, 28)
        btn.setIconSize(QSize(18, 18))
        btn.setIcon(QApplication.style().standardIcon(std_icon))
        return btn
