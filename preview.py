"""
preview.py — PreviewDrawer: ausklappbarer Vorschau-Bereich am rechten Rand.

Zeigt für das ausgewählte Element:
  - Bilder:  skaliertes Thumbnail via QPixmap
  - Texte:   erste 4 KB des Dateiinhalts
  - Andere:  großes Datei-Icon + Metadaten

Zustand (offen/zu, Breite) wird in QSettings gespeichert.
"""
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea, QSizePolicy, QFrame,
    QFileIconProvider,
)
from PySide6.QtCore import Qt, QSize, QSettings, QFileInfo
from PySide6.QtGui import QPixmap, QColor, QPainter, QFont

from config import ORG_NAME, SK_PREVIEW_WIDTH
from models import ExplorerModel


# Dateierweiterungen, die als Text angezeigt werden
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".conf", ".sh", ".bash", ".zsh",
    ".html", ".htm", ".css", ".xml", ".svg", ".log", ".csv",
}

# Dateierweiterungen, die als Bild angezeigt werden
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".ico", ".heic", ".heif",
}


class PreviewDrawer(QWidget):
    """Vorschau-Panel für die rechte Seite des MainWindow.

    Wird per F9 / Space ein-/ausgeblendet. Die Breite ist einstellbar und
    wird persistiert.
    """

    DEFAULT_WIDTH = 220

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(160)
        self.setMaximumWidth(500)

        # Gespeicherte Breite wiederherstellen
        s = QSettings(ORG_NAME, "Preview")
        w = s.value(SK_PREVIEW_WIDTH, self.DEFAULT_WIDTH, type=int)
        self.setFixedWidth(w)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── Vorschaubild / Icon ───────────────────────────────────────────────
        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setMinimumHeight(140)
        self._img_label.setMaximumHeight(200)
        self._img_label.setStyleSheet(
            "background: rgba(0,0,0,0.06); border-radius: 6px;"
        )
        layout.addWidget(self._img_label)

        # ── Dateiname ─────────────────────────────────────────────────────────
        self._name_label = QLabel()
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_label.setWordWrap(True)
        font = self._name_label.font()
        font.setBold(True)
        self._name_label.setFont(font)
        layout.addWidget(self._name_label)

        # ── Metadaten ─────────────────────────────────────────────────────────
        self._meta_label = QLabel()
        self._meta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._meta_label.setWordWrap(True)
        self._meta_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(self._meta_label)

        # ── Text-Vorschau ─────────────────────────────────────────────────────
        self._text_scroll = QScrollArea()
        self._text_scroll.setWidgetResizable(True)
        self._text_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._text_content = QLabel()
        self._text_content.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._text_content.setWordWrap(True)
        self._text_content.setTextFormat(Qt.TextFormat.PlainText)
        f = self._text_content.font()
        f.setFamily("Menlo, Consolas, monospace")
        f.setPointSize(10)
        self._text_content.setFont(f)
        self._text_scroll.setWidget(self._text_content)
        self._text_scroll.setVisible(False)
        layout.addWidget(self._text_scroll, 1)

        layout.addStretch(1)

        # Trennlinie links (zum Browser hin)
        self.setStyleSheet(
            "PreviewDrawer { border-left: 1px solid palette(mid); }"
        )

    def show_path(self, path: str):
        """Zeigt Vorschau und Metadaten für den gegebenen Pfad an."""
        fi = QFileInfo(path)
        if not fi.exists():
            self._clear()
            return

        suffix = Path(path).suffix.lower()
        name = fi.fileName()

        # ── Name ──────────────────────────────────────────────────────────────
        self._name_label.setText(name)

        # ── Metadaten ─────────────────────────────────────────────────────────
        if fi.isDir():
            try:
                count = len(os.listdir(path))
                meta = f"Ordner · {count} Elemente"
            except PermissionError:
                meta = "Ordner"
        else:
            size_str = ExplorerModel._fmt_size(fi.size())
            date_str = fi.lastModified().toString("dd.MM.yyyy  HH:mm")
            meta     = f"{size_str}\n{date_str}"
        self._meta_label.setText(meta)

        # ── Bild-Vorschau ─────────────────────────────────────────────────────
        if suffix in IMAGE_EXTENSIONS and fi.isFile():
            px = QPixmap(path)
            if not px.isNull():
                max_w = self._img_label.width() - 8
                max_h = self._img_label.height() - 8
                scaled = px.scaled(max_w, max_h,
                                   Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                self._img_label.setPixmap(scaled)
                # Auflösung zu Metadaten hinzufügen
                size_str = ExplorerModel._fmt_size(fi.size())
                date_str = fi.lastModified().toString("dd.MM.yyyy  HH:mm")
                self._meta_label.setText(
                    f"{size_str}\n{px.width()} × {px.height()} px\n{date_str}"
                )
                self._text_scroll.setVisible(False)
                return

        # ── Text-Vorschau ─────────────────────────────────────────────────────
        if suffix in TEXT_EXTENSIONS and fi.isFile():
            self._set_file_icon(path)
            try:
                content = Path(path).read_bytes()[:4096].decode("utf-8", errors="replace")
            except Exception:
                content = ""
            self._text_content.setText(content)
            self._text_scroll.setVisible(True)
            return

        # ── Standard: Datei-Icon ──────────────────────────────────────────────
        self._set_file_icon(path)
        self._text_scroll.setVisible(False)

    def _set_file_icon(self, path: str):
        """Zeigt das systemspezifische Datei-Icon im Vorschaubereich."""
        provider = QFileIconProvider()
        icon = provider.icon(QFileInfo(path))
        px = icon.pixmap(QSize(64, 64))
        self._img_label.setPixmap(px)

    def _clear(self):
        """Leert alle Vorschau-Elemente."""
        self._img_label.clear()
        self._name_label.clear()
        self._meta_label.clear()
        self._text_content.clear()
        self._text_scroll.setVisible(False)

    def clear_preview(self):
        """Öffentliche clear-Methode für MainWindow."""
        self._clear()

    def resizeEvent(self, event):
        """Speichert die aktuelle Breite in QSettings."""
        super().resizeEvent(event)
        s = QSettings(ORG_NAME, "Preview")
        s.setValue(SK_PREVIEW_WIDTH, self.width())
