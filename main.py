#!/usr/bin/env python3
"""
main.py — Einstiegspunkt für Fily.

Enthält nur: Plattform-Setup (Dark Mode, Icons, FDA-Dialog) und main().
Alle Klassen sind in separate Module ausgelagert.
"""
import sys
import os
import subprocess
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon, QColor, QPalette

from config import APP_NAME, ORG_NAME, VERSION, SK_FDA_HINT, asset_path
from mainwindow import MainWindow


def _linux_is_dark() -> bool:
    """Erkennt Dark Mode auf Linux.

    Reihenfolge: gsettings → GTK-Config-Dateien → dconf (letzter Fallback).
    Bug B6 Fix: dconf-Binärparsing ist jetzt letzter Fallback mit Try/Except.
    Wenn gsettings antwortet (kein Fehler), gilt sein Ergebnis — egal ob dark
    oder nicht; weitere Methoden werden dann nicht mehr geprüft.
    """
    # Methode 1: GNOME gsettings (zuverlässigste Methode)
    try:
        out = subprocess.check_output(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip().strip("'\"")
        # gsettings hat geantwortet → Ergebnis ist definitiv, kein weiteres Prüfen
        return "dark" in out.lower()
    except Exception:
        pass  # gsettings nicht verfügbar → nächste Methode

    # Methode 2: GTK-Config-Dateien (~/.config/gtk-4.0 oder gtk-3.0)
    for conf in [
        Path.home() / ".config" / "gtk-4.0" / "settings.ini",
        Path.home() / ".config" / "gtk-3.0" / "settings.ini",
    ]:
        try:
            text = conf.read_text(encoding="utf-8").lower()
            if ("gtk-application-prefer-dark-theme=1" in text or
                    "gtk-application-prefer-dark-theme=true" in text or
                    "color-scheme=prefer-dark" in text):
                return True
        except Exception:
            pass

    # Methode 3: dconf-Binärsuche (letzter Fallback, fehleranfällig)
    # Nur ausgeführt wenn gsettings nicht verfügbar und keine GTK-Konfig gefunden.
    try:
        data = (Path.home() / ".config" / "dconf" / "user").read_bytes()
        if b"prefer-dark" in data:
            return True
    except Exception:
        pass

    return False


def _apply_dark_palette(app: QApplication) -> None:
    """Apply a Fusion-based dark palette to the QApplication."""
    from PySide6.QtGui import QColor, QPalette
    app.setStyle("Fusion")
    p = QPalette()
    dark   = QColor(45, 45, 45)
    mid    = QColor(65, 65, 65)
    light  = QColor(90, 90, 90)
    text   = QColor(220, 220, 220)
    hi     = QColor(42, 130, 218)
    p.setColor(QPalette.ColorRole.Window,          dark)
    p.setColor(QPalette.ColorRole.WindowText,      text)
    p.setColor(QPalette.ColorRole.Base,            QColor(30, 30, 30))
    p.setColor(QPalette.ColorRole.AlternateBase,   dark)
    p.setColor(QPalette.ColorRole.ToolTipBase,     dark)
    p.setColor(QPalette.ColorRole.ToolTipText,     text)
    p.setColor(QPalette.ColorRole.Text,            text)
    p.setColor(QPalette.ColorRole.Button,          mid)
    p.setColor(QPalette.ColorRole.ButtonText,      text)
    p.setColor(QPalette.ColorRole.Mid,             mid)
    p.setColor(QPalette.ColorRole.Midlight,        QColor(75, 75, 75))
    p.setColor(QPalette.ColorRole.Dark,            QColor(35, 35, 35))
    p.setColor(QPalette.ColorRole.Shadow,          QColor(20, 20, 20))
    p.setColor(QPalette.ColorRole.BrightText,      QColor(255, 50, 50))
    p.setColor(QPalette.ColorRole.Link,            hi)
    p.setColor(QPalette.ColorRole.Highlight,       hi)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, light)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, light)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,       light)
    app.setPalette(p)


def _macos_show_fda_dialog(parent=None) -> None:
    """Zeigt einmalig pro App-Start einen Dialog für Full Disk Access (macOS).

    Nutzt QSettings um zu vermerken, ob der Dialog in dieser Sitzung bereits
    angezeigt wurde — verhindert wiederholtes Erscheinen beim Navigieren.
    """
    s = QSettings(ORG_NAME, "Permissions")
    if s.value("fda_hint_shown", False, type=bool):
        return
    s.setValue("fda_hint_shown", True)

    dlg = QMessageBox(parent)
    dlg.setWindowTitle("Zugriff eingeschränkt")
    dlg.setIcon(QMessageBox.Icon.Warning)
    dlg.setText(
        "<b>Fily hat keinen Zugriff auf diesen Ordner.</b><br><br>"
        "macOS schränkt den Zugriff auf bestimmte Verzeichnisse ein "
        "(z. B. Desktop, Dokumente, Downloads, externe Laufwerke).<br><br>"
        "Erlaube den Vollzugriff auf Dateien unter:<br>"
        "<i>Systemeinstellungen → Datenschutz &amp; Sicherheit → "
        "Vollzugriff auf Dateien</i>"
    )
    btn_settings = dlg.addButton("Zu Einstellungen", QMessageBox.ButtonRole.ActionRole)
    dlg.addButton("Schließen", QMessageBox.ButtonRole.RejectRole)
    dlg.exec()
    if dlg.clickedButton() == btn_settings:
        subprocess.run([
            "open",
            "x-apple.systempreferences:"
            "com.apple.preference.security?Privacy_AllFiles",
        ])


def main():
    # Linux: Umgebung vor QApplication vorbereiten.
    _linux_dark = False
    if sys.platform.startswith("linux"):
        # Ubuntu: disable global AppMenu integration — prevents menu bar from
        # disappearing immediately after click (BAMF/Unity proxy hijacks Qt menus).
        os.environ["UBUNTU_MENUPROXY"] = "0"

        # Unterdrücke harmlose GTK-Warnungen über nicht installierte Module
        # (canberra-gtk-module, pk-gtk-module) — diese sind optional und nicht
        # erforderlich für Fily. Erzwungene Überschreibung, da GTK_MODULES oft
        # von der Desktop-Session geerbt wird.
        os.environ["GTK_MODULES"] = ""

        # Unterdrücke Qt-D-Bus-Portal-Warnung "Could not register app ID"
        # — tritt auf wenn die App via Symlink gestartet wird und die D-Bus-
        # Verbindung bereits eine App-ID hat; die App funktioniert trotzdem.
        _existing_rules = os.environ.get("QT_LOGGING_RULES", "")
        _portal_rule = "qt.qpa.services=false"
        if _portal_rule not in _existing_rules:
            os.environ["QT_LOGGING_RULES"] = (
                f"{_existing_rules};{_portal_rule}" if _existing_rules else _portal_rule
            )

        # Dark-Mode-Erkennung VOR QApplication, damit QT_STYLE_OVERRIDE greift
        # bevor Qt das Plattform-Theme lädt (Fedora/GNOME überschreibt sonst
        # eine nachträglich gesetzte Palette).
        _linux_dark = _linux_is_dark()
        if _linux_dark:
            # Plattform-Theme entfernen — GNOME/GTK-Theme würde unsere
            # Fusion-Palette nach dem Start wieder überschreiben.
            os.environ.pop("QT_QPA_PLATFORMTHEME", None)
            os.environ["QT_STYLE_OVERRIDE"] = "Fusion"

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)

    # FDA-Hinweis-Flag zurücksetzen, damit er pro Sitzung einmal erscheinen kann.
    if sys.platform == "darwin":
        QSettings(ORG_NAME, "Permissions").setValue("fda_hint_shown", False)

    # App-Icon setzen (Taskleiste / Dock / Alt+Tab)
    if sys.platform == "win32":
        # Windows: .ico verwenden; AppUserModelID setzen damit Taskleiste
        # das Icon der .exe zuordnet (statt Python-Interpreter-Icon).
        try:
            import ctypes
            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "com.fily.app"
                )
        except Exception:
            pass
        icon_path = asset_path("assets", "icons", "windows", "icon.ico")
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
    elif sys.platform.startswith("linux"):
        icon_path = asset_path("assets", "icons", "linux", "256x256.png")
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
        # GNOME verknüpft die laufende App mit dem .desktop-Eintrag über
        # diesen Namen — ohne dies zeigt die Taskleiste das Zahnrad-Icon.
        app.setDesktopFileName("fily")

    # Linux: Fusion dark palette anwenden (Erkennung bereits oben erfolgt).
    if _linux_dark:
        _apply_dark_palette(app)

    if sys.platform == "darwin":
        app.setApplicationDisplayName(APP_NAME)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
