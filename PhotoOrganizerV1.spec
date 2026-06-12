# -*- mode: python ; coding: utf-8 -*-
# Photo Organizer v1.0 - PyInstaller Build Spec
# One-folder 배포: dist\PhotoOrganizer_v1\ 폴더 전체를 배포하면 됩니다.

block_cipher = None

a = Analysis(
    ['main_gui.py'],
    pathex=['src', 'vendor'],
    binaries=[],
    datas=[
        # vendor 디렉토리의 Pillow 번들 포함
        ('vendor/PIL', 'PIL'),
        ('vendor/pillow-12.2.0.dist-info', 'pillow-12.2.0.dist-info'),
    ],
    hiddenimports=[
        'sqlite3',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'photos',
        'photos.gui',
        'photos.cli',
        'photos.database',
        'photos.scanner',
        'photos.planning',
        'photos.hashing',
        'photos.review',
        'photos.reports',
        'photos.pairing',
        'photos.manifest',
        'photos.models',
        'photos.dry_run',
        'photos.win_fs',
        'photos.env_check',
        'photos.classification',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'pytest',
        'ruff',
        'IPython',
        'notebook',
    ],
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
    name='PhotoOrganizer_v1',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # 콘솔 창 숨김 (GUI 앱)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # 아이콘 파일 경로 (없으면 기본 아이콘 사용)
)

# One-folder 배포: dist\PhotoOrganizer_v1\ 폴더 전체를 배포
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
