from __future__ import annotations

import shutil
import sqlite3
import unittest
from pathlib import Path

from photos.store import Store


class TestSchemaContract(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".test-tmp/test_schema_contract").resolve()
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "photos.sqlite"
        self.store = Store(self.db_path)
        self.store.init_schema()
        self.conn = self.store.conn

    def tearDown(self) -> None:
        self.store.close()

    def _table_columns(self, table_name: str) -> set[str]:
        rows = self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row["name"]) for row in rows}

    def test_required_goal_tables_and_columns_exist(self) -> None:
        required = {
            "folder_samples": {"id", "folder_path", "sample_type", "path", "name", "size_bytes", "dates_json", "gps_place_id"},
            "places": {"id", "lat_bucket", "lon_bucket", "label", "provider", "confidence", "raw_json", "updated_at"},
            "folder_place_summaries": {
                "folder_path",
                "dominant_places_json",
                "gps_file_count",
                "non_gps_file_count",
                "updated_at",
            },
            "name_groups": {"id", "normalized_name", "member_count", "size_variants", "date_range_json", "status"},
            "candidate_members": {"candidate_id", "path", "member_role", "evidence_json"},
            "folder_pair_relations": {
                "id",
                "folder_a",
                "folder_b",
                "matched_name_count",
                "same_size_count",
                "same_exif_count",
                "derivative_count",
                "collision_count",
                "dominant_place",
                "date_range_json",
                "confidence",
                "reason_json",
            },
            "date_audit_groups": {"id", "folder_path", "issue_type", "confidence", "evidence_json", "status"},
            "date_audit_items": {
                "group_id",
                "path",
                "filename_date",
                "folder_date",
                "exif_date",
                "filesystem_date",
                "proposed_canonical_date",
                "status",
            },
            "metadata_edit_suggestions": {
                "id",
                "target_type",
                "target_path",
                "proposed_value",
                "source",
                "status",
                "reason_json",
            },
            "llm_packets": {"id", "packet_type", "path", "root_folder", "created_at", "row_count", "sha256", "settings_json"},
        }
        for table_name, required_columns in required.items():
            with self.subTest(table=table_name):
                cols = self._table_columns(table_name)
                self.assertTrue(required_columns.issubset(cols), f"{table_name} missing columns: {required_columns - cols}")

    def test_duplicate_candidates_goal_columns_exist(self) -> None:
        cols = self._table_columns("duplicate_candidates")
        self.assertTrue(
            {"group_type", "confidence", "recommended_action", "reason_json", "created_at"}.issubset(cols),
            f"duplicate_candidates missing GOAL columns: { {'group_type', 'confidence', 'recommended_action', 'reason_json', 'created_at'} - cols }",
        )

    def test_required_status_values_exist_at_schema_level(self) -> None:
        expected = {
            "existence_state": {"seen", "not_seen_this_scan", "confirmed_missing"},
            "duplicate_candidates.group_type": {
                "probable_duplicate",
                "transferred_derivative",
                "same_name_collision",
                "folder_pair_burst",
                "requires_review",
            },
            "plan_actions.action_type": {
                "move",
                "rename_move",
                "keep_separate",
                "hold",
                "metadata_override",
                "metadata_write_candidate",
            },
            "transfer_method": {"same_volume_move", "copy_verify_cleanup"},
            "batch_status": {"planned", "dry_run_passed", "running", "verified", "committed", "failed", "held", "cancelled"},
            "item_status": {"pending", "moved", "copied", "verified", "source_changed", "collision", "failed", "held"},
            "llm_review_items.status": {"pending_approval", "approved", "rejected", "superseded"},
        }
        rows = self.conn.execute("SELECT status_key, status_value FROM required_status_values").fetchall()
        actual: dict[str, set[str]] = {}
        for row in rows:
            actual.setdefault(str(row["status_key"]), set()).add(str(row["status_value"]))
        for key, values in expected.items():
            with self.subTest(status_key=key):
                self.assertIn(key, actual, f"missing status key: {key}")
                self.assertTrue(values.issubset(actual[key]), f"{key} missing values: {values - actual[key]}")

    def test_schema_version_recorded(self) -> None:
        row = self.conn.execute("SELECT value FROM app_state WHERE key='schema_version'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(str(row["value"]), "2")


if __name__ == "__main__":
    unittest.main()
