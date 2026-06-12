"""
Photo Organizer v1.0 - Windows GUI 진입점
PyInstaller 빌드 시 이 파일을 엔트리포인트로 사용합니다.
"""
from __future__ import annotations

import sys
from pathlib import Path

# vendor 디렉토리를 sys.path에 추가 (Pillow 번들 지원)
_APP_DIR = Path(__file__).resolve().parent
_VENDOR_DIR = _APP_DIR / "vendor"
if _VENDOR_DIR.exists() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

# src 디렉토리를 sys.path에 추가
_SRC_DIR = _APP_DIR / "src"
if _SRC_DIR.exists() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from photos.gui import launch

if __name__ == "__main__":
    raise SystemExit(launch())
