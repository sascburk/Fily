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
from PySide6.QtCore import Qt, QSize, QSettings, QFileInfo, QThread, Signal, QTimer
from PySide6.QtGui import QPixmap, QColor, QPainter, QFont, QImage

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
HEAVY_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".zip", ".tar", ".gz", ".xz", ".7z",
    ".iso", ".dmg", ".pkg", ".mp3", ".wav", ".flac",
}
PREVIEW_SIZE_LIMIT = 64 * 1024 * 1024  # 64 MB


class _PreviewWorker(QThread):
    """Lädt teure Vorschau-Inhalte im Hintergrund."""

    loaded = Signal(int, dict)  # request_id, payload

    def __init__(self, request_id: int, path: str, max_w: int, max_h: int, parent=None):
        super().__init__(parent)
        self._request_id = request_id
        self._path = path
        self._max_w = max_w
        self._max_h = max_h

    def run(self):
        fi = QFileInfo(self._path)
        if not fi.exists():
            self.loaded.emit(self._request_id, {"ok": False})
            return

        suffix = Path(self._path).suffix.lower()
        date_str = fi.lastModified().toString("dd.MM.yyyy  HH:mm")

        if self.isInterruptionRequested():
            return
        if fi.isFile() and (fi.size() > PREVIEW_SIZE_LIMIT or suffix in HEAVY_EXTENSIONS):
            meta = f"{ExplorerModel._fmt_size(fi.size())}\n{date_str}"
            self.loaded.emit(self._request_id, {"ok": True, "kind": "icon", "meta": meta})
            return

        # Bilder: QImage im Worker laden (QPixmap erst im UI-Thread)
        if suffix in IMAGE_EXTENSIONS and fi.isFile():
            img = QImage(self._path)
            if not img.isNull():
                if self.isInterruptionRequested():
                    return
                scaled = img.scaled(
                    max(1, self._max_w),
                    max(1, self._max_h),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                meta = (
                    f"{ExplorerModel._fmt_size(fi.size())}\n"
                    f"{img.width()} × {img.height()} px\n"
                    f"{date_str}"
                )
                self.loaded.emit(
                    self._request_id,
                    {"ok": True, "kind": "image", "image": scaled, "meta": meta},
                )
                return

        # Textdateien: nur die ersten 4 KB laden
        if suffix in TEXT_EXTENSIONS and fi.isFile():
            if self.isInterruptionRequested():
                return
            try:
                content = Path(self._path).read_bytes()[:4096].decode("utf-8", errors="replace")
            except Exception:
                content = ""
            meta = f"{ExplorerModel._fmt_size(fi.size())}\n{date_str}"
            self.loaded.emit(
                self._request_id,
                {"ok": True, "kind": "text", "text": content, "meta": meta},
            )
            return

        # Standard
        if fi.isDir():
            meta = "Ordner"
        else:
            meta = f"{ExplorerModel._fmt_size(fi.size())}\n{date_str}"
        self.loaded.emit(
            self._request_id,
            {"ok": True, "kind": "icon", "meta": meta},
        )


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
        self._icon_provider = QFileIconProvider()
        self._request_id = 0
        self._worker: _PreviewWorker | None = None
        self._pending_path: str | None = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(80)
        self._debounce.timeout.connect(self._start_preview_load)

        # Gespeicherte Breite als bevorzugte Breite setzen (nicht fixiert,
        # damit der Splitter weiterhin die Größe anpassen kann)
        s = QSettings(ORG_NAME, "Preview")
        self._preferred_width = s.value(SK_PREVIEW_WIDTH, self.DEFAULT_WIDTH, type=int)

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
        self._text_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._text_content = QLabel()
        self._text_content.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._text_content.setWordWrap(True)
        self._text_content.setTextFormat(Qt.TextFormat.PlainText)
        # Nur lesen, aber Textauswahl/Kopieren erlauben.
        self._text_content.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._text_content.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        f = self._text_content.font()
        # QFont.setFamily nimmt nur einen Namen — plattformspezifisch wählen
        import sys as _sys
        mono = "Menlo" if _sys.platform == "darwin" else "Consolas" if _sys.platform == "win32" else "monospace"
        f.setFamily(mono)
        f.setPointSize(10)
        self._text_content.setFont(f)
        self._text_scroll.setWidget(self._text_content)
        self._text_scroll.setVisible(False)
        layout.addWidget(self._text_scroll, 1)

        # Trennlinie links (zum Browser hin)
        self.setStyleSheet(
            "PreviewDrawer { border-left: 1px solid palette(mid); }"
        )

    def show_path(self, path: str):
        """Zeigt Vorschau und Metadaten für den gegebenen Pfad an."""
        self._request_id += 1
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()

        fi = QFileInfo(path)
        if not fi.exists():
            self._clear()
            return

        name = fi.fileName()

        # ── Name ──────────────────────────────────────────────────────────────
        self._name_label.setText(name)
        self._set_file_icon(path)
        self._text_scroll.setVisible(False)
        self._text_content.clear()
        self._meta_label.setText("Lade Vorschau …")
        self._pending_path = path
        self._debounce.start()

    def _start_preview_load(self):
        if not self._pending_path:
            return
        request_id = self._request_id
        path = self._pending_path
        max_w = self._img_label.width() - 8
        max_h = self._img_label.height() - 8
        self._worker = _PreviewWorker(request_id, path, max_w, max_h, self)
        self._worker.loaded.connect(self._on_loaded_preview)
        self._worker.start()

    def _on_loaded_preview(self, request_id: int, payload: dict):
        if request_id != self._request_id:
            return
        if not payload.get("ok"):
            self._clear()
            return
        self._meta_label.setText(payload.get("meta", ""))
        kind = payload.get("kind")
        if kind == "image":
            image = payload.get("image")
            if isinstance(image, QImage):
                self._img_label.setPixmap(QPixmap.fromImage(image))
            self._text_scroll.setVisible(False)
            return
        if kind == "text":
            self._text_content.setText(payload.get("text", ""))
            self._text_scroll.setVisible(True)
            return
        self._text_scroll.setVisible(False)

    def _set_file_icon(self, path: str):
        """Zeigt das systemspezifische Datei-Icon im Vorschaubereich."""
        icon = self._icon_provider.icon(QFileInfo(path))
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

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self._preferred_width, 400)

    def resizeEvent(self, event):
        """Speichert die aktuelle Breite in QSettings."""
        super().resizeEvent(event)
        if self.width() > 0:
            self._preferred_width = self.width()
            s = QSettings(ORG_NAME, "Preview")
            s.setValue(SK_PREVIEW_WIDTH, self.width())
