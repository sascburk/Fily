# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-Spec-Datei für Fily
# Erstellt mit:  pyinstaller OSX_Explorer.spec

import sys
from pathlib import Path

block_cipher = None

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
    icon='assets/icons/windows/icon.ico',  # Windows
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
    icon='assets/icons/macos/icon.icns',
    bundle_identifier='com.fily.app',
    version='1.1.0',
    info_plist={
        'CFBundleName':              'Fily',
        'CFBundleDisplayName':       'Fily',
        'CFBundleVersion':           '1.1.0',
        'CFBundleShortVersionString':'1.1.0',
        'NSHighResolutionCapable':   True,
        'NSSupportsAutomaticGraphicsSwitching': True,
        'LSApplicationCategoryType': 'public.app-category.utilities',
        'NSRequiresAquaSystemAppearance': False,  # Dark Mode unterstützen
        # Dateizugriffs-Berechtigungen für sandboxlose App
        'NSDocumentsFolderUsageDescription':  'Dateizugriff für Fily',
        'NSDownloadsFolderUsageDescription':  'Dateizugriff für Fily',
        'NSDesktopFolderUsageDescription':    'Dateizugriff für Fily',
    },
)
