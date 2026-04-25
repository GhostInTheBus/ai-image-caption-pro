# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('bin/exiftool', 'bin')],
    datas=[('assets', 'assets')],
    hiddenimports=['app.ui.floating_window', 'app.ui.progress_panel', 'app.ui.settings_dialog', 'app.ui.tray', 'app.core.agent', 'app.core.captioner', 'app.core.exiftool', 'app.core.job_db', 'app.models'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PIL', 'Pillow', 'numpy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AIPhotoCaptionPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AIPhotoCaptionPro',
)
app = BUNDLE(
    coll,
    name='AI Photo Caption Pro.app',
    icon='assets/icon.icns',
    bundle_identifier='com.aiphotocaptionpro.app',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1',
        'NSHumanReadableCopyright': '© 2026 AI Photo Caption Pro',
        'LSMinimumSystemVersion': '13.0',
    },
)
