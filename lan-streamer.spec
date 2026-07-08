# -*- mode: python ; coding: utf-8 -*-
import os
import re
import sys

# Read version from src/lan_streamer/__init__.py
version = '0.0.0'
try:
    with open(os.path.join('src', 'lan_streamer', '__init__.py'), 'r', encoding='utf-8') as f:
        match = re.search(r'__version__\s*=\s*[\'"]([^\'"]+)[\'"]', f.read())
        if match:
            version = match.group(1)
except Exception as e:
    print(f"Warning: could not read version from __init__.py: {e}")

is_darwin = sys.platform == 'darwin'

a = Analysis(
    ['src/entrypoint.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('alembic.ini', '.'),
        ('alembic', 'alembic'),
    ],
    hiddenimports=[
        'alembic',
        'alembic.runtime.migration',
        'logging.config',
        'PySide6',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtNetwork',
    ],
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
        name=f'lan-streamer-{version}',
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
        name=f'lan-streamer-{version}',
    )
    app = BUNDLE(
        coll,
        name=f'lan-streamer-{version}.app',
        icon=None,
        bundle_identifier='com.lanstreamer.app',
        info_plist={
            'CFBundleShortVersionString': version,
            'CFBundleVersion': version,
            'NSHumanReadableCopyright': 'Copyright © 2026',
        }
    )
else:
    exe_name = f'lan-streamer-{version}'
    exe_args = {
        'name': exe_name,
        'debug': False,
        'bootloader_ignore_signals': False,
        'strip': False,
        'upx': True,
        'upx_exclude': [],
        'runtime_tmpdir': None,
        'console': False,
        'disable_windowed_traceback': False,
        'argv_emulation': False,
        'target_arch': None,
        'codesign_identity': None,
        'entitlements_file': None,
    }
    if sys.platform == 'win32':
        def parse_version(version_str):
            parts = []
            for part in version_str.split('.'):
                digits = ''.join(c for c in part if c.isdigit())
                parts.append(int(digits) if digits else 0)
            while len(parts) < 4:
                parts.append(0)
            return tuple(parts[:4])

        version_tuple = parse_version(version)
        version_info_content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple},
    prodvers={version_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'LanStreamer'),
            StringStruct('FileDescription', 'Lightweight media library manager for local playback with Jellyfin synchronization'),
            StringStruct('FileVersion', '{version}'),
            StringStruct('InternalName', 'lan-streamer'),
            StringStruct('LegalCopyright', 'Copyright © 2026'),
            StringStruct('OriginalFilename', 'lan-streamer-{version}.exe'),
            StringStruct('ProductName', 'LAN Streamer'),
            StringStruct('ProductVersion', '{version}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
        version_file_path = 'file_version_info.txt'
        with open(version_file_path, 'w', encoding='utf-8') as f:
            f.write(version_info_content)
        exe_args['version'] = version_file_path

    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        **exe_args
    )
