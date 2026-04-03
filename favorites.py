"""
favorites.py — FavoritesPanel: Liquid-Glass-Seitenleiste mit Favoritenliste.

Besonderheit: Schriftgröße der Einträge ist 13 pt (größer als die Dateiliste
mit 11 pt), damit Favoriten auf einen Blick lesbar sind.
Die Seitenleiste beginnt am absoluten oberen Fensterrand.
"""
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListView, QFrame, QToolButton, QSizePolicy,
    QMenu, QInputDialog, QFileDialog, QAbstractItemView, QLabel,
)
from PySide6.QtCore import Qt, QModelIndex, QEvent, Signal, QSize, QItemSelectionModel
from PySide6.QtGui import (
    QPainter, QColor, QPalette, QLinearGradient, QBrush, QPen,
)

from models import FavoritesModel


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
