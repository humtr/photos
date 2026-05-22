from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from photos.store import Store


class TestPhase1Indexes(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".test-tmp/test_phase1_indexes").resolve()
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.root / "photos.sqlite")
        self.store.init_schema()
        self.conn = self.store.conn

    def tearDown(self) -> None:
        self.store.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def _indexes(self, table_name: str) -> set[str]:
        rows = self.conn.execute(f"PRAGMA index_list({table_name})").fetchall()
        return {str(row["name"]) for row in rows}

    def _plan_text(self, sql: str, params: tuple = ()) -> str:
        rows = self.conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
        return "\n".join(str(row["detail"]).upper() for row in rows)

    def test_required_phase1_indexes_exist(self) -> None:
        expected = {
            "media_files": {
                "idx_media_scan_state_path",
                "idx_media_scan_suffix_size",
                "idx_media_scan_name",
                "idx_media_scan_folder_name",
            },
            "folder_nodes": {
                "idx_folder_nodes_scan_parent_path",
                "idx_folder_nodes_scan_last_seen",
            },
            "duplicate_candidates": {
                "idx_duplicate_candidates_scan_status_type",
                "idx_duplicate_candidates_scan_group_type",
            },
            "metadata_audits": {"idx_metadata_audits_scan_issue_folder"},
            "date_audit_groups": {"idx_date_audit_groups_status"},
        }
        for table_name, index_names in expected.items():
            with self.subTest(table=table_name):
                actual = self._indexes(table_name)
                self.assertTrue(index_names.issubset(actual), f"{table_name} missing indexes: {index_names - actual}")

    def test_media_state_path_query_uses_index(self) -> None:
        plan = self._plan_text(
            """
            SELECT path FROM media_files
            WHERE scan_root_id=? AND existence_state=?
            ORDER BY path
            LIMIT 100
            """,
            (1, "seen"),
        )
        self.assertIn("IDX_MEDIA_SCAN_STATE_PATH", plan)

    def test_duplicate_bucket_queries_use_indexes(self) -> None:
        suffix_size_plan = self._plan_text(
            """
            SELECT path FROM media_files
            WHERE scan_root_id=? AND suffix=? AND size_bytes=?
            """,
            (1, ".jpg", 12345),
        )
        self.assertIn("IDX_MEDIA_SCAN_SUFFIX_SIZE", suffix_size_plan)

        name_plan = self._plan_text(
            """
            SELECT path FROM media_files
            WHERE scan_root_id=? AND name=?
            """,
            (1, "IMG_0001.JPG"),
        )
        self.assertIn("IDX_MEDIA_SCAN_NAME", name_plan)

    def test_folder_and_date_audit_queries_use_indexes(self) -> None:
        folder_plan = self._plan_text(
            """
            SELECT path FROM folder_nodes
            WHERE scan_root_id=? AND parent_path=?
            ORDER BY path
            """,
            (1, "D:/Photos"),
        )
        self.assertIn("IDX_FOLDER_NODES_SCAN_PARENT_PATH", folder_plan)

        audit_plan = self._plan_text(
            """
            SELECT id FROM metadata_audits
            WHERE scan_root_id=? AND issue_type=? AND folder_path=?
            """,
            (1, "date_conflict_cluster", "D:/Photos/Event"),
        )
        self.assertIn("IDX_METADATA_AUDITS_SCAN_ISSUE_FOLDER", audit_plan)

    def test_synthetic_400k_media_page_uses_bounded_page_fetch(self) -> None:
        self.conn.execute(
            """
            WITH RECURSIVE seq(x) AS (
                SELECT 0
                UNION ALL
                SELECT x + 1 FROM seq WHERE x < 399999
            )
            INSERT INTO media_files(
                scan_root_id, path, folder_path, name, stem, suffix, media_type,
                size_bytes, ctime_ns, mtime_ns, existence_state
            )
            SELECT
                1,
                'D:/bulk/' || x || '.jpg',
                'D:/bulk/' || (x / 10000),
                printf('IMG_%06d.JPG', x),
                printf('IMG_%06d', x),
                '.jpg',
                'photo',
                100000 + x,
                x,
                x,
                'seen'
            FROM seq
            """
        )
        self.conn.commit()

        plan = self._plan_text(
            """
            SELECT path, folder_path, name, size_bytes, mtime_ns
            FROM media_files
            WHERE scan_root_id=? AND existence_state=?
            ORDER BY path
            LIMIT ? OFFSET ?
            """,
            (1, "seen", 10_000, 120_000),
        )
        self.assertIn("IDX_MEDIA_SCAN_STATE_PATH", plan)

        rows = self.conn.execute(
            """
            SELECT path, folder_path, name, size_bytes, mtime_ns
            FROM media_files
            WHERE scan_root_id=? AND existence_state=?
            ORDER BY path
            LIMIT ? OFFSET ?
            """,
            (1, "seen", 10_000, 120_000),
        ).fetchall()
        total = self.conn.execute("SELECT COUNT(*) AS c FROM media_files WHERE scan_root_id=?", (1,)).fetchone()["c"]
        self.assertEqual(400_000, int(total))
        self.assertEqual(10_000, len(rows))


if __name__ == "__main__":
    unittest.main()
