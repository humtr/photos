"""
환경 점검 모듈 — Python 버전, 외부 도구, Windows 특화 항목을 검사합니다.
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import sys
from pathlib import Path

RAW_TOOL_CANDIDATES = ["darktable-cli", "rawtherapee-cli", "magick"]
MIN_PYTHON = (3, 11)


def _check_long_path_support() -> dict:
    """Windows 긴 경로(>260자) 지원 여부를 확인합니다."""
    result: dict = {"supported": None, "note": ""}
    if platform.system() != "Windows":
        result["supported"] = True
        result["note"] = "non-Windows: no limit"
        return result
    try:
        import winreg  # type: ignore[import]
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
        )
        val, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
        result["supported"] = bool(val)
        result["note"] = "registry key found" if val else "registry key is 0 — enable via Group Policy or registry"
    except Exception as exc:
        result["supported"] = False
        result["note"] = f"could not read registry: {exc}"
    return result


def _check_disk_space(path: str | None = None) -> dict:
    """지정 경로(또는 현재 디렉토리)의 디스크 여유 공간을 확인합니다."""
    check_path = path or os.getcwd()
    try:
        usage = shutil.disk_usage(check_path)
        return {
            "path": check_path,
            "free_bytes": usage.free,
            "total_bytes": usage.total,
            "free_gb": round(usage.free / 1024**3, 2),
        }
    except Exception as exc:
        return {"path": check_path, "error": str(exc)}


def _check_pillow() -> dict:
    """Pillow(PIL) 가용성과 버전을 확인합니다."""
    spec = importlib.util.find_spec("PIL")
    if spec is None:
        # vendor 디렉토리 확인
        vendor_pil = Path(__file__).resolve().parents[2] / "vendor" / "PIL"
        if vendor_pil.exists():
            return {"available": True, "source": "vendor", "version": "bundled"}
        return {"available": False, "source": None, "version": None}
    try:
        import PIL  # type: ignore[import]
        return {"available": True, "source": "installed", "version": getattr(PIL, "__version__", "unknown")}
    except Exception:
        return {"available": False, "source": None, "version": None}


def check_environment(archive_root: str | None = None) -> dict:
    """전체 환경을 점검하고 결과 딕셔너리를 반환합니다."""
    py_ver = sys.version_info[:2]
    tools = {
        "git": shutil.which("git"),
        "ffmpeg": shutil.which("ffmpeg"),
        "exiftool": shutil.which("exiftool"),
    }
    raw_tools = {name: shutil.which(name) for name in RAW_TOOL_CANDIDATES}
    has_raw_tool = any(v for v in raw_tools.values())

    result = {
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
            "meets_minimum": py_ver >= MIN_PYTHON,
            "minimum_required": f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "is_windows": platform.system() == "Windows",
        },
        "tools": tools,
        "raw_tool_candidates": raw_tools,
        "has_raw_tool": has_raw_tool,
        "pyside6_available": importlib.util.find_spec("PySide6") is not None,
        "pillow": _check_pillow(),
        "long_path_support": _check_long_path_support(),
        "disk_space": _check_disk_space(archive_root),
    }

    # 전체 준비 상태 요약
    warnings: list[str] = []
    if not result["python"]["meets_minimum"]:
        warnings.append(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ 필요 (현재: {result['python']['version']})")
    if not result["pyside6_available"]:
        warnings.append("PySide6 미설치 — GUI를 사용하려면 'pip install PySide6' 실행")
    if not result["pillow"]["available"]:
        warnings.append("Pillow 미설치 — EXIF/이미지 처리에 필요")
    if not tools["exiftool"]:
        warnings.append("ExifTool 미설치 — 정확한 EXIF 날짜 추출에 권장")
    if not has_raw_tool:
        warnings.append("RAW 변환 도구 없음 (darktable-cli / rawtherapee-cli / magick 중 하나 권장)")
    if platform.system() == "Windows" and not result["long_path_support"].get("supported"):
        warnings.append("Windows 긴 경로 미지원 — 260자 초과 경로에서 오류 발생 가능")

    result["warnings"] = warnings
    result["ready"] = len(warnings) == 0

    return result


def main(argv: list[str] | None = None) -> int:
    _ = argv
    print(json.dumps(check_environment(), indent=2, sort_keys=True, ensure_ascii=False))
    return 0
