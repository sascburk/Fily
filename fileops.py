"""
fileops.py — Dateioperationen: Kopieren, Verschieben, Löschen, Archivieren.

Alle Funktionen sind zustandslos und arbeiten nur mit Pfaden.
Sie werden von FileBrowser und dem CopyWorker genutzt.

Bug B2 Fix: get_clipboard_paths() liest auch System-Clipboard-URLs.
Bug B3 Fix: safe_trash() warnt vor permanentem Löschen.
"""
import os
import shutil
import sys
import subprocess
import zipfile
import tarfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from send2trash import send2trash as _send2trash

from PySide6.QtWidgets import QMessageBox


def build_ops(src_paths: list[str], dest_dir: str) -> list[tuple[str, str]]:
    """Erstellt (src, dst)-Paare mit automatischer Namenskonflikt-Auflösung.

    Wenn der Zielname bereits existiert, wird ' (1)', ' (2)' etc. angehängt.
    """
    ops = []
    for src in src_paths:
        dst = Path(dest_dir) / Path(src).name
        if dst.exists():
            base, ext = dst.stem, dst.suffix
            i = 1
            while dst.exists():
                dst = Path(dest_dir) / f"{base} ({i}){ext}"
                i += 1
        ops.append((src, str(dst)))
    return ops


def _windows_send_to_recycle_bin(path: str) -> bool:
    """Fallback für Windows-Papierkorb via PowerShell/.NET.

    Wird nur genutzt, wenn send2trash fehlschlägt.
    """
    if sys.platform != "win32":
        return False
    p = Path(path)
    # Einfache Escapes für PowerShell-Stringliteral.
    ps_path = str(p).replace("'", "''")
    is_dir = p.is_dir()
    ps_cmd = (
        "Add-Type -AssemblyName Microsoft.VisualBasic;"
        f"$p='{ps_path}';"
        "if (Test-Path -LiteralPath $p) {"
        + (
            "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory("
            "$p,'OnlyErrorDialogs','SendToRecycleBin');"
            if is_dir
            else
            "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
            "$p,'OnlyErrorDialogs','SendToRecycleBin');"
        )
        + "exit 0 } else { exit 1 }"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return res.returncode == 0
    except Exception:
        return False


def _linux_send_to_trash(path: str) -> bool:
    """Fallback für Linux gemäß Freedesktop-Trash-Spezifikation."""
    if not sys.platform.startswith("linux"):
        return False

    src = Path(path)
    if not src.exists():
        return False

    trash_base = Path.home() / ".local" / "share" / "Trash"
    files_dir = trash_base / "files"
    info_dir = trash_base / "info"
    files_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)

    stem = src.name
    dst = files_dir / stem
    i = 1
    while dst.exists():
        dst = files_dir / f"{stem}.{i}"
        i += 1

    deleted_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    info_path = info_dir / f"{dst.name}.trashinfo"
    info_content = (
        "[Trash Info]\n"
        f"Path={quote(str(src.resolve()))}\n"
        f"DeletionDate={deleted_at}\n"
    )
    try:
        shutil.move(str(src), str(dst))
        info_path.write_text(info_content, encoding="utf-8")
        return True
    except Exception:
        try:
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            if info_path.exists():
                info_path.unlink()
        except Exception:
            pass
        return False


def safe_trash(path: str, parent=None) -> bool:
    """Legt eine Datei/Ordner in den Papierkorb.

    Bug B3 Fix: Wenn send2trash fehlschlägt, wird der User gefragt ob er
    permanent löschen möchte — kein stilles Löschen mehr.

    Args:
        path:   Pfad zur Datei/Ordner.
        parent: Eltern-Widget für den Warn-Dialog.

    Returns:
        True wenn gelöscht (Papierkorb oder permanent), False wenn abgebrochen.
    """
    try:
        _send2trash(path)
        return True
    except Exception:
        # Windows-Fallback: PowerShell/.NET Recycle Bin API.
        if _windows_send_to_recycle_bin(path):
            return True
        # Linux-Fallback: Freedesktop Trash manuell.
        if _linux_send_to_trash(path):
            return True

        # Papierkorb nicht verfügbar — User fragen ob permanent löschen
        reply = QMessageBox.warning(
            parent, "Papierkorb nicht verfügbar",
            f"'{Path(path).name}' kann nicht in den Papierkorb gelegt werden.\n\n"
            "Element permanent löschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return True
        except OSError as e:
            QMessageBox.warning(parent, "Fehler", f"Löschen fehlgeschlagen:\n{e}")
            return False


def _clear_dir_contents(path: Path) -> None:
    """Löscht den kompletten Inhalt eines Verzeichnisses (nicht das Verzeichnis selbst)."""
    if not path.exists():
        return
    for entry in path.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def empty_trash() -> tuple[bool, str]:
    """Leert den systemnahen Papierkorb der aktuellen Plattform.

    Returns:
        (ok, message) wobei message bei Fehlern einen Grund enthält.
    """
    try:
        if sys.platform == "win32":
            res = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Clear-RecycleBin -Force -ErrorAction Stop",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if res.returncode != 0:
                msg = (res.stderr or res.stdout or "Unbekannter Fehler").strip()
                return False, msg
            return True, ""

        if sys.platform == "darwin":
            _clear_dir_contents(Path.home() / ".Trash")
            return True, ""

        # Linux/Freedesktop-Spezifikation
        trash_base = Path.home() / ".local" / "share" / "Trash"
        _clear_dir_contents(trash_base / "files")
        _clear_dir_contents(trash_base / "info")
        return True, ""
    except Exception as e:
        return False, str(e)


def reveal_in_filemanager(path: str):
    """Zeigt Datei/Ordner im nativen Dateimanager an (cross-platform)."""
    try:
        if sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", "-R", path], capture_output=True)
        elif sys.platform == "win32":
            import subprocess
            subprocess.run(["explorer", "/select,", path.replace("/", "\\")])
        else:
            import subprocess
            subprocess.run(["xdg-open", str(Path(path).parent)], capture_output=True)
    except Exception:
        pass


def get_clipboard_paths() -> list[str]:
    """Liest Dateipfade aus dem System-Clipboard.

    Bug B2 Fix: Gibt URLs aus QApplication.clipboard() zurück — damit
    funktioniert Paste auch nach Kopieren in Finder/Explorer/Terminal.
    """
    from PySide6.QtWidgets import QApplication
    mime = QApplication.clipboard().mimeData()
    if mime and mime.hasUrls():
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
    return []


def compress_to_zip(src_paths: list[str], dest_zip: str,
                    progress_callback=None) -> bool:
    """Komprimiert Dateien/Ordner in eine ZIP-Datei.

    Args:
        src_paths:         Liste von Quellpfaden (Dateien oder Ordner).
        dest_zip:          Ziel-Pfad der ZIP-Datei.
        progress_callback: Optional callable(current, total) für Fortschritt.

    Returns:
        True bei Erfolg, False bei Fehler.
    """
    try:
        all_files: list[tuple[str, str]] = []   # (abs_path, arcname)
        for src in src_paths:
            src_p = Path(src)
            if src_p.is_dir():
                for f in src_p.rglob("*"):
                    if f.is_file():
                        all_files.append((str(f), str(f.relative_to(src_p.parent))))
            else:
                all_files.append((src, src_p.name))

        total = len(all_files)
        with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, (abs_path, arcname) in enumerate(all_files):
                if progress_callback:
                    should_continue = progress_callback(i + 1, total)
                    if should_continue is False:
                        raise InterruptedError()
                zf.write(abs_path, arcname)
        return True
    except InterruptedError:
        # Partielle ZIP-Datei bei Abbruch entfernen.
        try:
            Path(dest_zip).unlink(missing_ok=True)
        except Exception:
            pass
        return False
    except Exception:
        return False


def extract_archive(src: str, dest_dir: str) -> bool:
    """Entpackt eine ZIP- oder TAR-Datei.

    Unterstützte Formate: .zip, .tar, .tar.gz, .tgz, .tar.bz2, .tar.xz

    Returns:
        True bei Erfolg, False bei Fehler oder unbekanntem Format.
    """
    src_p = Path(src)
    suffix = "".join(src_p.suffixes).lower()
    try:
        if suffix == ".zip":
            with zipfile.ZipFile(src, "r") as zf:
                zf.extractall(dest_dir)
        elif suffix in (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz"):
            with tarfile.open(src, "r:*") as tf:
                tf.extractall(dest_dir)
        else:
            return False
        return True
    except Exception:
        return False
