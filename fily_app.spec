# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-Spec-Datei für Fily
# Erstellt mit:  pyinstaller fily_app.spec
#
# macOS  → Fily.app  (Bundle, mehrere Dateien)
# Windows → Fily.exe  (One-File)
# Linux   → Fily       (One-File)

import sys
import shutil
import tempfile
from pathlib import Path

block_cipher = None

IS_MAC   = sys.platform == "darwin"
IS_WIN   = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

if IS_WIN:
    # Icon in lokales Temp-Verzeichnis kopieren — Synology Drive / Netzlaufwerke
    # blockieren Low-Level-Lesezugriffe von PyInstaller (OSError 22 in CopyIcons).
    _src = Path('.').resolve() / 'assets' / 'icons' / 'windows' / 'icon.ico'
    _tmp = Path(tempfile.gettempdir()) / 'fily_build_icon.ico'
    shutil.copy2(str(_src), str(_tmp))
    icon = str(_tmp)
elif IS_MAC:
    icon = 'assets/icons/macos/icon.icns'
else:
    icon = 'assets/icons/linux/icon_256.png'

a = Analysis(
    ['main.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[
        ('assets/icons', 'assets/icons'),
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtNetwork',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if IS_MAC:
    # ── macOS: klassisches Folder-Bundle (.app) ────────────────────────────
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='Fily',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='Fily',
    )

    app = BUNDLE(
        coll,
        name='Fily.app',
        icon=icon,
        bundle_identifier='com.fily.app',
        version='1.1.1',
        info_plist={
            'CFBundleName':              'Fily',
            'CFBundleDisplayName':       'Fily',
            'CFBundleVersion':           '1.1.1',
            'CFBundleShortVersionString':'1.1.1',
            'NSHighResolutionCapable':   True,
            'NSSupportsAutomaticGraphicsSwitching': True,
            'LSApplicationCategoryType': 'public.app-category.utilities',
            'NSRequiresAquaSystemAppearance': False,
            'NSDocumentsFolderUsageDescription':  'Dateizugriff für Fily',
            'NSDownloadsFolderUsageDescription':  'Dateizugriff für Fily',
            'NSDesktopFolderUsageDescription':    'Dateizugriff für Fily',
        },
    )

else:
    # ── Windows / Linux: Folder-Distribution ──────────────────────────────
    # One-File schlägt mit PySide6 auf Netzlaufwerken (z. B. Synology Drive)
    # fehl und erzeugt sehr grosse Archive mit AV-Problemen.
    # Folder-Mode ist stabiler; zum Verteilen einfach dist/Fily/ zippen.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='Fily',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='Fily',
    )
