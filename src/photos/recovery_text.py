from __future__ import annotations


def summarize_service_failure(detail: str, default: str = "작업이 차단되었습니다.") -> str:
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    if not lines:
        return default

    headline = lines[0]
    for line in lines[1:]:
        if line.startswith("다음 안전 조치:"):
            next_safe_action = line.partition(":")[2].strip()
            if next_safe_action:
                return f"{headline} (다음 안전 조치: {next_safe_action})"
            break
    return headline
