"""
Windows 파일 시스템 유틸리티 — 긴 경로, 권한, 파일 잠금 처리.

Windows 이외 환경에서도 안전하게 임포트할 수 있도록 설계되었습니다.
"""
from __future__ import annotations

import os
import platform
import shutil
import time
from pathlib import Path

_IS_WINDOWS = platform.system() == "Windows"

# Windows에서 260자 제한을 우회하기 위한 접두사
_WIN_LONG_PREFIX = "\\\\?\\"
MAX_WINDOWS_PATH = 260


def to_long_path(path: Path | str) -> str:
    """Windows에서 긴 경로 접두사를 붙인 문자열을 반환합니다.

    Windows 이외 환경에서는 그대로 반환합니다.
    """
    p = str(Path(path).resolve())
    if not _IS_WINDOWS:
        return p
    if p.startswith(_WIN_LONG_PREFIX):
        return p
    # UNC 경로(\\server\share)는 \\?\UNC\server\share 형식으로 변환
    if p.startswith("\\\\"):
        return _WIN_LONG_PREFIX + "UNC\\" + p[2:]
    return _WIN_LONG_PREFIX + p


def is_path_too_long(path: Path | str) -> bool:
    """경로가 Windows 최대 길이를 초과하는지 확인합니다."""
    if not _IS_WINDOWS:
        return False
    return len(str(Path(path).resolve())) >= MAX_WINDOWS_PATH


def safe_move(src: Path | str, dst: Path | str, *, retries: int = 3, delay: float = 0.5) -> None:
    """파일을 안전하게 이동합니다.

    - Windows 긴 경로를 자동으로 처리합니다.
    - 파일 잠금(PermissionError) 발생 시 지정된 횟수만큼 재시도합니다.
    - 대상 폴더가 없으면 자동으로 생성합니다.

    Args:
        src: 원본 파일 경로.
        dst: 대상 파일 경로.
        retries: 파일 잠금 시 재시도 횟수.
        delay: 재시도 간격(초).

    Raises:
        FileNotFoundError: 원본 파일이 존재하지 않을 때.
        PermissionError: 재시도 후에도 파일 잠금이 해제되지 않을 때.
        OSError: 기타 파일 시스템 오류.
    """
    src_path = Path(src)
    dst_path = Path(dst)

    if not src_path.exists():
        raise FileNotFoundError(f"원본 파일을 찾을 수 없습니다: {src_path}")

    dst_path.parent.mkdir(parents=True, exist_ok=True)

    # 대상 경로가 이미 존재하면 충돌 방지를 위해 이름 변경
    if dst_path.exists():
        stem = dst_path.stem
        suffix = dst_path.suffix
        idx = 2
        while dst_path.exists():
            dst_path = dst_path.with_name(f"{stem}_{idx}{suffix}")
            idx += 1

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            if _IS_WINDOWS and (is_path_too_long(src_path) or is_path_too_long(dst_path)):
                # 긴 경로 처리: os.rename 사용 (shutil.move는 내부적으로 긴 경로 미지원)
                long_src = to_long_path(src_path)
                long_dst = to_long_path(dst_path)
                os.makedirs(os.path.dirname(long_dst), exist_ok=True)
                os.rename(long_src, long_dst)
            else:
                shutil.move(str(src_path), str(dst_path))
            return
        except PermissionError as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(delay)
        except OSError as exc:
            raise OSError(f"파일 이동 실패 ({src_path} → {dst_path}): {exc}") from exc

    raise PermissionError(
        f"파일 잠금으로 인해 이동 실패 ({retries}회 시도): {src_path}"
    ) from last_exc


def validate_move_plan(
    plans: list[dict[str, str]],
    archive_root: Path | str,
) -> list[str]:
    """이동 계획의 유효성을 검사하고 오류 목록을 반환합니다.

    검사 항목:
    - 원본 파일 존재 여부
    - 대상 경로가 archive_root 하위인지 (루트 이탈 방지)
    - 대상 경로 중복 여부
    - Windows 긴 경로 초과 여부

    Args:
        plans: [{"source_path": ..., "planned_path": ...}, ...] 형식의 계획 목록.
        archive_root: 허용된 대상 루트 경로.

    Returns:
        오류 메시지 목록. 비어 있으면 검증 통과.
    """
    root = Path(archive_root).resolve()
    errors: list[str] = []
    seen: set[str] = set()

    for p in plans:
        src = p.get("source_path", "")
        dst = p.get("planned_path", "")

        try:
            src_path = Path(src).resolve()
            dst_path = Path(dst).resolve()
        except Exception:
            errors.append(f"경로 파싱 오류: src={src!r}, dst={dst!r}")
            continue

        # 대상 루트 이탈 검사
        try:
            dst_path.relative_to(root)
        except ValueError:
            errors.append(f"대상 루트 이탈: {dst_path} (허용 루트: {root})")

        # 대상 경로 중복 검사
        key = str(dst_path).lower()
        if key in seen:
            errors.append(f"대상 경로 중복: {dst_path}")
        seen.add(key)

        # Windows 긴 경로 검사
        if _IS_WINDOWS and is_path_too_long(dst_path):
            errors.append(f"경로 길이 초과 ({len(str(dst_path))}자): {dst_path}")

    return errors
