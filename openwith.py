"""
openwith.py — Ermittelt installierte Apps für eine Datei (cross-platform).

macOS:   mdfind /Applications → .app bundles
Windows: Registry HKEY_CLASSES_ROOT
Linux:   xdg-mime + .desktop-Dateien
"""
import sys
import subprocess
from pathlib import Path


def get_apps_for_file(path: str) -> list[tuple[str, str]]:
    """Gibt eine Liste von (App-Name, Pfad/Befehl) zurück.

    Returns:
        Liste von (display_name, launch_command) oder leere Liste.
    """
    if sys.platform == "darwin":
        return _macos_apps(path)
    if sys.platform == "win32":
        return _windows_apps(path)
    return _linux_apps(path)


def open_with(path: str, app_command: str):
    """Öffnet eine Datei mit der angegebenen App."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", app_command, path])
        elif sys.platform == "win32":
            subprocess.Popen([app_command, path], shell=True)
        else:
            subprocess.Popen([app_command, path])
    except Exception:
        pass


def _macos_apps(path: str) -> list[tuple[str, str]]:
    """macOS: Listet .app-Bundles in /Applications via mdfind."""
    try:
        result = subprocess.check_output(
            ["mdfind", "kMDItemContentTypeTree == 'com.apple.application-bundle'",
             "-onlyin", "/Applications"],
            timeout=2, stderr=subprocess.DEVNULL,
        ).decode()
        apps = []
        for line in result.strip().splitlines():
            p = Path(line.strip())
            if p.exists() and p.suffix == ".app":
                apps.append((p.stem, str(p)))
        return apps[:20]  # Maximal 20 Apps anzeigen
    except Exception:
        return []


def _linux_apps(path: str) -> list[tuple[str, str]]:
    """Linux: xdg-mime + .desktop-Dateien aus Standard-Verzeichnissen."""
    apps = []
    try:
        mime = subprocess.check_output(
            ["xdg-mime", "query", "filetype", path],
            timeout=2, stderr=subprocess.DEVNULL,
        ).decode().strip()
        if not mime:
            return []
        desktop_dirs = [
            Path("/usr/share/applications"),
            Path.home() / ".local" / "share" / "applications",
        ]
        for d in desktop_dirs:
            if not d.exists():
                continue
            for f in d.glob("*.desktop"):
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    if mime in content or "MimeType=*" in content:
                        name = ""
                        exec_cmd = ""
                        for line in content.splitlines():
                            if line.startswith("Name=") and not name:
                                name = line[5:]
                            if line.startswith("Exec=") and not exec_cmd:
                                exec_cmd = line[5:].split("%")[0].strip()
                        if name and exec_cmd:
                            apps.append((name, exec_cmd))
                except Exception:
                    continue
    except Exception:
        pass
    return apps[:15]


def _windows_apps(path: str) -> list[tuple[str, str]]:
    """Windows: Registry-Lookup für die Dateiendung."""
    try:
        import winreg
        suffix = Path(path).suffix.lower()
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, suffix) as k:
            prog_id = winreg.QueryValue(k, "")
        open_cmd_key = f"{prog_id}\\shell\\open\\command"
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, open_cmd_key) as k:
            cmd = winreg.QueryValue(k, "")
        return [(prog_id, cmd.split('"')[1] if '"' in cmd else cmd.split()[0])]
    except Exception:
        return []
