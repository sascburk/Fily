# fily_app.spec — PyInstaller-Spec für Fily 2.0
# Alle Module sind auf oberster Ebene (flat structure) → kein Paket nötig.
#
# macOS:   → dist/Fily.app  (BUNDLE, kein Terminal, .icns-Icon)
# Windows: → dist/Fily.exe  (EXE, kein Terminal, .ico-Icon)
# Linux:   → dist/Fily      (EXE, kein Terminal; Name wie in EXE(..., name='Fily'))

import sys

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('assets', 'assets'),   # Icons und andere Assets
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtWidgets',
        'PySide6.QtGui',
        'PySide6.QtMultimedia',
        'send2trash',
        # Alle Fily-Module explizit listen (PyInstaller findet lokale Module
        # manchmal nicht automatisch beim --onefile-Build)
        'config', 'models', 'workers', 'fileops', 'dialogs',
        'browser', 'mainwindow', 'favorites', 'addressbar',
        'treeview', 'preview', 'toolbar', 'search_worker', 'openwith',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Plattformspezifisches Icon
if sys.platform == 'darwin':
    _icon = 'assets/icons/macos/icon.icns'
elif sys.platform == 'win32':
    _icon = 'assets/icons/windows/icon.ico'
else:
    _icon = None

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Fily',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # Kein Terminal-Fenster
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)

# macOS: .app-Bundle erstellen
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='Fily.app',
        icon='assets/icons/macos/icon.icns',
        bundle_identifier='com.fily.app',
        info_plist={
            'CFBundleDisplayName': 'Fily',
            'CFBundleShortVersionString': '2.0',
            'NSHighResolutionCapable': True,
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'LSMinimumSystemVersion': '12.0',
        },
    )
