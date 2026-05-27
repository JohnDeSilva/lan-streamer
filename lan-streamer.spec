# -*- mode: python ; coding: utf-8 -*-
import sys

is_darwin = sys.platform == 'darwin'

a = Analysis(
    ['src/entrypoint.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('alembic.ini', '.'),
        ('alembic', 'alembic'),
    ],
    hiddenimports=['alembic', 'alembic.runtime.migration', 'logging.config'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if is_darwin:
    exe = EXE(
        pyz,
        a.scripts,
        exclude_binaries=True,
        name='lan-streamer',
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
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='lan-streamer',
    )
    app = BUNDLE(
        coll,
        name='lan-streamer.app',
        icon=None,
        bundle_identifier=None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='lan-streamer',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
