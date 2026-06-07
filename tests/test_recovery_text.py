from __future__ import annotations

import unittest

from photos.recovery_text import summarize_service_failure


class RecoveryTextTests(unittest.TestCase):
    def test_summarize_service_failure_defaults_when_empty(self) -> None:
        self.assertEqual(summarize_service_failure(""), "작업이 차단되었습니다.")

    def test_summarize_service_failure_keeps_headline_without_hint(self) -> None:
        self.assertEqual(
            summarize_service_failure("서비스 실행 차단\n서비스 dry-run 차단 사유:\n- 파일 없음"),
            "서비스 실행 차단",
        )

    def test_summarize_service_failure_includes_next_safe_action(self) -> None:
        self.assertEqual(
            summarize_service_failure(
                "서비스 실행 차단\n경고: 승인 필요\n다음 안전 조치: resume_batch"
            ),
            "서비스 실행 차단 (다음 안전 조치: resume_batch)",
        )


if __name__ == "__main__":
    unittest.main()
