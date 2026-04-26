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
    QWidget, QVBoxLayout, QHBoxLayout, QListView, QFrame, QToolButton, QSizePolicy,
    QMenu, QInputDialog, QFileDialog, QAbstractItemView, QLabel, QColorDialog,
)
from PySide6.QtCore import Qt, QModelIndex, QEvent, Signal, QSize, QItemSelectionModel, QSettings
from PySide6.QtGui import (
    QPainter, QColor, QPalette, QLinearGradient, QBrush, QPen,
)

from config import ORG_NAME, SK_FAV_BG_COLOR
from models import FavoritesModel


# ──────────────────────────────────────────────────────────────────────────────
class FavoritesPanel(QWidget):
    navigate = Signal(str)
    add_fav  = Signal(str)
    window_close = Signal()
    window_minimize = Signal()
    window_maximize_toggle = Signal()
    window_drag_start = Signal(object)   # global QPoint
    window_drag_move = Signal(object)    # global QPoint
    window_drag_end = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._window_controls_visible = True
        self.setMinimumWidth(150)
        self.setMaximumWidth(300)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        s = QSettings(ORG_NAME, "MainWindow")
        color_val = s.value(SK_FAV_BG_COLOR, "")
        self._custom_color: QColor | None = QColor(color_val) if color_val else None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header_bar = QWidget()
        self._header_bar.setFixedHeight(56)
        header_layout = QVBoxLayout(self._header_bar)
        header_layout.setContentsMargins(8, 2, 4, 2)
        header_layout.setSpacing(0)

        self._header_controls = QWidget()
        controls_layout = QHBoxLayout(self._header_controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)

        self._header = QLabel("  Favoriten")
        hf = self._header.font()
        if hf.pointSize() > 0:
            hf.setPointSize(13)
        hf.setBold(True)
        self._header.setFont(hf)
        self._header.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._header_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._header_bar.customContextMenuRequested.connect(self._color_ctx_menu)

        self.btn_min = QToolButton()
        self.btn_min.setText("−")
        self.btn_min.setFixedSize(13, 13)
        self.btn_min.setToolTip("Minimieren")
        self.btn_min.clicked.connect(self.window_minimize)

        self.btn_max = QToolButton()
        self.btn_max.setText("+")
        self.btn_max.setFixedSize(13, 13)
        self.btn_max.setToolTip("Maximieren / Wiederherstellen")
        self.btn_max.clicked.connect(self.window_maximize_toggle)

        self.btn_close = QToolButton()
        self.btn_close.setText("✕")
        self.btn_close.setFixedSize(13, 13)
        self.btn_close.setToolTip("Schließen")
        self.btn_close.clicked.connect(self.window_close)

        for b in (self.btn_min, self.btn_max, self.btn_close):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setAutoRaise(True)
            bf = b.font()
            if bf.pointSize() > 0:
                bf.setPointSize(9)
            bf.setBold(True)
            b.setFont(bf)
            b.setStyleSheet("border: none; color: transparent;")

        self.btn_close.setStyleSheet(
            "QToolButton { background: #ff5f57; border-radius: 6px; color: transparent; padding: 0 0 1px 0; }"
            "QToolButton:hover { background: #ff3b30; color: #5c0000; padding: 0 0 1px 0; }"
        )
        self.btn_min.setStyleSheet(
            "QToolButton { background: #ffbd2e; border-radius: 6px; color: transparent; padding: 0 0 1px 0; }"
            "QToolButton:hover { background: #f5a623; color: #6b4d00; padding: 0 0 1px 0; }"
        )
        self.btn_max.setStyleSheet(
            "QToolButton { background: #28c840; border-radius: 6px; color: transparent; padding: 0 0 1px 0; }"
            "QToolButton:hover { background: #20b538; color: #0a4d17; padding: 0 0 1px 0; }"
        )

        # macOS Reihenfolge: Schließen, Minimieren, Maximieren
        controls_layout.addWidget(self.btn_close)
        controls_layout.addWidget(self.btn_min)
        controls_layout.addWidget(self.btn_max)
        controls_layout.addStretch(1)

        header_layout.addWidget(self._header_controls)
        header_layout.addWidget(self._header)
        layout.addWidget(self._header_bar)
        self._header_bar.installEventFilter(self)
        self._header_controls.installEventFilter(self)
        self._header.installEventFilter(self)

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

    def set_window_controls_visible(self, visible: bool):
        self._window_controls_visible = bool(visible)
        self._header_controls.setVisible(self._window_controls_visible)
        self._header_bar.setFixedHeight(56 if self._window_controls_visible else 34)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        r = self.rect()

        if self._custom_color:
            c = self._custom_color
            base_top = QColor(c.red(), c.green(), c.blue(), 220)
            base_bot = QColor(
                max(0, c.red() - 15), max(0, c.green() - 15), max(0, c.blue() - 15), 230
            )
            dark = c.lightness() < 128
            if dark:
                specular = QColor(120, 140, 180,  45)
                border_c = QColor(90,  100, 130, 130)
                tint     = QColor(80,  100, 160,  18)
            else:
                specular = QColor(255, 255, 255, 160)
                border_c = QColor(180, 190, 215, 140)
                tint     = QColor(180, 200, 255,  22)
        else:
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
        if obj in (self._header_bar, self._header_controls, self._header):
            if not self._window_controls_visible:
                return super().eventFilter(obj, event)
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self.window_drag_start.emit(event.globalPosition().toPoint())
                return True
            if event.type() == QEvent.Type.MouseMove and (event.buttons() & Qt.MouseButton.LeftButton):
                self.window_drag_move.emit(event.globalPosition().toPoint())
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self.window_drag_end.emit()
                return True
            if event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
                self.window_maximize_toggle.emit()
                return True
        if obj is self.view:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._clicked(self.view.currentIndex())
                    return True
                count = self.model.rowCount()
                cur   = self.view.currentIndex().row()
                if event.key() == Qt.Key.Key_Down and count and cur >= count - 1:
                    target = self.model.index(0)
                    self.view.setCurrentIndex(target)
                    self.view.selectionModel().select(
                        target, QItemSelectionModel.SelectionFlag.ClearAndSelect
                    )
                    return True
                if event.key() == Qt.Key.Key_Up and count and cur <= 0:
                    target = self.model.index(count - 1)
                    self.view.setCurrentIndex(target)
                    self.view.selectionModel().select(
                        target, QItemSelectionModel.SelectionFlag.ClearAndSelect
                    )
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
        menu.addSeparator()
        color_action = menu.addAction("Hintergrundfarbe anpassen …")
        reset_action = menu.addAction("Standardfarbe wiederherstellen")

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
        elif action == color_action:
            self._pick_color()
        elif action == reset_action:
            self._reset_color()

    def _color_ctx_menu(self, pos):
        menu = QMenu(self)
        color_action = menu.addAction("Hintergrundfarbe anpassen …")
        reset_action = menu.addAction("Standardfarbe wiederherstellen")
        action = menu.exec(self._header_bar.mapToGlobal(pos))
        if action == color_action:
            self._pick_color()
        elif action == reset_action:
            self._reset_color()

    def _pick_color(self):
        initial = self._custom_color or self.palette().color(QPalette.ColorRole.Window)
        color = QColorDialog.getColor(initial, self, "Hintergrundfarbe wählen")
        if color.isValid():
            self._custom_color = color
            QSettings(ORG_NAME, "MainWindow").setValue(SK_FAV_BG_COLOR, color.name())
            self.update()

    def _reset_color(self):
        self._custom_color = None
        QSettings(ORG_NAME, "MainWindow").remove(SK_FAV_BG_COLOR)
        self.update()

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
