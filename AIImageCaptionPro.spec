# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('bin/exiftool', 'bin')],
    datas=[('assets', 'assets')],
    hiddenimports=[
        # core
        'app.core.agent',
        'app.core.captioner',
        'app.core.exiftool',
        'app.core.job_db',
        'app.models',
        # ui — all panels
        'app.ui.main_window',
        'app.ui.drop_panel',
        'app.ui.queue_panel',
        'app.ui.quick_settings_panel',
        'app.ui.status_bar',
        'app.ui.progress_panel',
        'app.ui.settings_dialog',
        'app.ui.style',
        # legacy (kept in repo, not entry point)
        'app.ui.floating_window',
        'app.ui.tray',
    ],
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
    name='AIImageCaptionPro',
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
    name='AIImageCaptionPro',
)
app = BUNDLE(
    coll,
    name='AI Image Caption Pro.app',
    icon='assets/icon.icns',
    bundle_identifier='com.aiimagecaptionpro.app',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': '2.0.0',
        'CFBundleVersion': '2',
        'NSHumanReadableCopyright': '© 2026 AI Image Caption Pro',
        'LSMinimumSystemVersion': '13.0',
    },
)
