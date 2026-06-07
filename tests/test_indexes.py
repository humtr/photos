from __future__ import annotations

import sqlite3
import unittest
import sys
from pathlib import Path
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from photos.database import connect


class TestDatabaseIndexes(unittest.TestCase):
    def setUp(self) -> None:
        self.con = connect(":memory:")

    def tearDown(self) -> None:
        self.con.close()

    def _indexes(self) -> set[str]:
        rows = self.con.execute("PRAGMA index_list(media_files)").fetchall()
        return {row["name"] for row in rows}

    def _plan_text(self, sql: str, params: tuple = ()) -> str:
        rows = self.con.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
        return "\n".join(str(row["detail"]).upper() for row in rows)

    def test_indexes_exist(self) -> None:
        actual_indexes = self._indexes()
        expected_indexes = {
            "idx_media_suffix_size",
            "idx_media_name",
            "idx_media_exists_path",
        }
        for index_name in expected_indexes:
            self.assertIn(index_name, actual_indexes, f"Missing index: {index_name}")

    def test_queries_use_indexes(self) -> None:
        # Test that suffix & size_bytes query uses idx_media_suffix_size
        suffix_size_plan = self._plan_text(
            "SELECT path FROM media_files WHERE suffix = ? AND size_bytes = ?",
            (".jpg", 1024)
        )
        self.assertIn("IDX_MEDIA_SUFFIX_SIZE", suffix_size_plan)

        # Test that name query uses idx_media_name
        name_plan = self._plan_text(
            "SELECT path FROM media_files WHERE name = ?",
            ("IMG_0001.JPG",)
        )
        self.assertIn("IDX_MEDIA_NAME", name_plan)

        # Test that disk existence check query uses idx_media_exists_path
        exists_plan = self._plan_text(
            "SELECT path FROM media_files WHERE exists_on_disk = ?",
            (1,)
        )
        self.assertIn("IDX_MEDIA_EXISTS_PATH", exists_plan)

        # Also test disk existence list query uses idx_media_exists_path
        list_exists_plan = self._plan_text(
            "SELECT path FROM media_files WHERE exists_on_disk = 1 ORDER BY path"
        )
        self.assertIn("IDX_MEDIA_EXISTS_PATH", list_exists_plan)


if __name__ == "__main__":
    unittest.main()
