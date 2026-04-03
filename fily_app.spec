# fily_app.spec — PyInstaller-Spec für Fily 2.0
# Alle Module sind auf oberster Ebene (flat structure) → kein Paket nötig.

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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='fily',
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
    # Windows: Icon
    icon='assets/icons/windows/icon.ico',
)
