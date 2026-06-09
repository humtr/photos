# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

# Windows GUI 빌드를 위한 설정
block_cipher = None

a = Analysis(
    ['src/photos/__main__.py'],
    pathex=['src', 'vendor'],
    binaries=[],
    datas=[
        # vendor 디렉토리의 PIL 등 외부 패키지 포함
        ('vendor/PIL', 'PIL'),
    ],
    hiddenimports=[
        'sqlite3',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',  # 레거시 GUI 제거
        'unittest',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 개발/디버깅을 위한 콘솔 모드 여부 (출시 시 False 권장)
console_mode = False

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PhotoOrganizer_v1',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=console_mode,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# One-folder 배포 (압축 해제 지연 방지 및 외부 도구 번들링 용이)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PhotoOrganizer_v1',
)
