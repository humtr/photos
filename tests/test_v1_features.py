"""
Photo Organizer v1.0 신규 기능 테스트

- planning.py: 파일명/폴더명 날짜 파싱 우선순위
- win_fs.py: 이동 계획 유효성 검사
- env_check.py: 환경 점검 결과 구조
"""
from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from photos.planning import _parse_filename_date, _parse_parent_date, row_date
from photos.win_fs import validate_move_plan
from photos.env_check import check_environment


# ─── planning: 날짜 파싱 ──────────────────────────────────────────────────────

class TestFilenameDateParsing:
    def test_iso_format(self):
        dt = _parse_filename_date("IMG_2023-05-01.jpg")
        assert dt == datetime(2023, 5, 1)

    def test_compact_format(self):
        dt = _parse_filename_date("20230501_120000.jpg")
        assert dt == datetime(2023, 5, 1)

    def test_underscore_format(self):
        dt = _parse_filename_date("photo_2023_05_01.jpg")
        assert dt == datetime(2023, 5, 1)

    def test_no_date_returns_none(self):
        assert _parse_filename_date("IMG_0001.jpg") is None

    def test_invalid_month_returns_none(self):
        # 월이 13이면 ValueError 발생 → None 반환
        assert _parse_filename_date("20231301.jpg") is None


class TestParentDateParsing:
    def test_folder_with_date(self):
        dt = _parse_parent_date("2023-05/trip")
        assert dt == datetime(2023, 5, 1)

    def test_folder_without_date(self):
        assert _parse_parent_date("vacation/photos") is None


class TestRowDate:
    """row_date 함수의 날짜 우선순위를 검증합니다."""

    def _make_row(self, name: str, parent_key: str, mtime_ns: int) -> sqlite3.Row:
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute(
            "CREATE TABLE t (name TEXT, parent_key TEXT, mtime_ns INTEGER)"
        )
        con.execute("INSERT INTO t VALUES (?, ?, ?)", (name, parent_key, mtime_ns))
        return con.execute("SELECT * FROM t").fetchone()

    def test_filename_date_wins_over_mtime(self):
        # 파일명에 2023-01-15가 있으면 mtime(2020년)보다 우선
        mtime_2020 = int(datetime(2020, 6, 1).timestamp() * 1e9)
        row = self._make_row("IMG_2023-01-15.jpg", "photos", mtime_2020)
        assert row_date(row) == datetime(2023, 1, 15)

    def test_parent_date_wins_over_mtime(self):
        mtime_2020 = int(datetime(2020, 6, 1).timestamp() * 1e9)
        row = self._make_row("IMG_0001.jpg", "2022-08/trip", mtime_2020)
        assert row_date(row).year == 2022
        assert row_date(row).month == 8

    def test_mtime_fallback(self):
        mtime_ns = int(datetime(2021, 3, 10).timestamp() * 1e9)
        row = self._make_row("IMG_0001.jpg", "photos", mtime_ns)
        dt = row_date(row)
        assert dt.year == 2021
        assert dt.month == 3


# ─── win_fs: 이동 계획 유효성 검사 ───────────────────────────────────────────

class TestValidateMovePlan:
    def test_valid_plan_returns_no_errors(self, tmp_path):
        archive = tmp_path / "PICTURES"
        plans = [
            {"source_path": str(tmp_path / "a.jpg"), "planned_path": str(archive / "2023/2023-01/a.jpg")},
            {"source_path": str(tmp_path / "b.jpg"), "planned_path": str(archive / "2023/2023-01/b.jpg")},
        ]
        errors = validate_move_plan(plans, archive)
        assert errors == []

    def test_root_escape_detected(self, tmp_path):
        archive = tmp_path / "PICTURES"
        plans = [
            {"source_path": str(tmp_path / "a.jpg"), "planned_path": str(tmp_path / "OTHER" / "a.jpg")},
        ]
        errors = validate_move_plan(plans, archive)
        assert any("루트 이탈" in e for e in errors)

    def test_duplicate_destination_detected(self, tmp_path):
        archive = tmp_path / "PICTURES"
        dst = str(archive / "2023/2023-01/dup.jpg")
        plans = [
            {"source_path": str(tmp_path / "a.jpg"), "planned_path": dst},
            {"source_path": str(tmp_path / "b.jpg"), "planned_path": dst},
        ]
        errors = validate_move_plan(plans, archive)
        assert any("중복" in e for e in errors)

    def test_empty_plan_is_valid(self, tmp_path):
        assert validate_move_plan([], tmp_path / "PICTURES") == []


# ─── env_check: 환경 점검 ─────────────────────────────────────────────────────

class TestCheckEnvironment:
    def test_returns_required_keys(self):
        result = check_environment()
        for key in ("python", "platform", "tools", "pyside6_available", "pillow", "warnings", "ready"):
            assert key in result, f"키 누락: {key}"

    def test_python_meets_minimum(self):
        result = check_environment()
        # 테스트 환경은 Python 3.11+ 이어야 함
        assert result["python"]["meets_minimum"] is True

    def test_warnings_is_list(self):
        result = check_environment()
        assert isinstance(result["warnings"], list)

    def test_pillow_available_via_vendor(self):
        result = check_environment()
        # vendor 디렉토리에 PIL이 있으므로 available=True 이어야 함
        assert result["pillow"]["available"] is True
