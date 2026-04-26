"""
toolbar.py — Moderne Browser-Toolbar mit SVG-Icons (Fallback: Qt-Standard-Icons).

Schaltflächen: Zurück | Vor | Hoch | Aktualisieren | Neuer Ordner | Ansicht wechseln.
Die Toolbar ist kompakt (28×28 px Icons) und hat keine Text-Labels.
"""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QToolButton, QSizePolicy, QApplication, QStyle
from PySide6.QtCore import Qt, Signal, QSize, QEvent
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
    new_tab_clicked    = Signal()
    window_drag_start  = Signal(object)  # global QPoint
    window_drag_move   = Signal(object)  # global QPoint
    window_drag_end    = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_area_enabled = True
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
        self.btn_new_tab = QToolButton()
        self.btn_new_tab.setText("+")
        self.btn_new_tab.setToolTip("Neuer Tab  (Ctrl+T)")
        self.btn_new_tab.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_new_tab.setFixedSize(28, 28)

        # Zurück/Vor zu Beginn deaktiviert (keine Navigationhistorie vorhanden)
        self.btn_back.setEnabled(False)
        self.btn_forward.setEnabled(False)

        self.btn_back.clicked.connect(self.back_clicked)
        self.btn_forward.clicked.connect(self.forward_clicked)
        self.btn_up.clicked.connect(self.up_clicked)
        self.btn_reload.clicked.connect(self.reload_clicked)
        self.btn_new_dir.clicked.connect(self.new_folder_clicked)
        self.btn_view.clicked.connect(self.view_toggle)
        self.btn_new_tab.clicked.connect(self.new_tab_clicked)

        for btn in (self.btn_back, self.btn_forward, self.btn_up,
                    self.btn_reload, self.btn_new_dir, self.btn_view):
            layout.addWidget(btn)

        self._drag_area = QWidget()
        self._drag_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._drag_area.setCursor(Qt.CursorShape.OpenHandCursor)
        self._drag_area.installEventFilter(self)
        layout.addWidget(self._drag_area, 1)
        layout.addWidget(self.btn_new_tab)

    def set_drag_area_enabled(self, enabled: bool):
        self._drag_area_enabled = bool(enabled)
        self._drag_area.setVisible(self._drag_area_enabled)

    def _btn(self, tip: str, std_icon) -> QToolButton:
        """Erstellt einen kompakten Icon-Button mit Qt-Standard-Icon."""
        btn = QToolButton()
        btn.setToolTip(tip)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setFixedSize(28, 28)
        btn.setIconSize(QSize(18, 18))
        btn.setIcon(QApplication.style().standardIcon(std_icon))
        return btn

    def eventFilter(self, obj, event):
        if obj is getattr(self, "_drag_area", None):
            if not self._drag_area_enabled:
                return False
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_area.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.window_drag_start.emit(event.globalPosition().toPoint())
                return True
            if event.type() == QEvent.Type.MouseMove and (event.buttons() & Qt.MouseButton.LeftButton):
                self.window_drag_move.emit(event.globalPosition().toPoint())
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self._drag_area.setCursor(Qt.CursorShape.OpenHandCursor)
                self.window_drag_end.emit()
                return True
        return super().eventFilter(obj, event)
