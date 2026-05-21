from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from photos.duplicates import analyze_duplicates
from photos.store import Store


class TestPhase2DuplicateScreening(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".test-tmp/test_phase2_duplicates").resolve()
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.root / "photos.sqlite")
        self.store.init_schema()
        self.conn = self.store.conn

    def tearDown(self) -> None:
        self.store.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def _insert_media(
        self,
        path: str,
        folder: str,
        name: str,
        size: int,
        exif_datetime: str | None = None,
    ) -> None:
        stem = Path(name).stem
        suffix = Path(name).suffix.lower()
        self.conn.execute(
            """
            INSERT INTO media_files(
                scan_root_id,path,folder_path,name,stem,suffix,media_type,
                size_bytes,ctime_ns,mtime_ns,exif_datetime,existence_state
            )
            VALUES(1,?,?,?,?,?,'photo',?,0,?,?,'seen')
            """,
            (path, folder, name, stem, suffix, size, size, exif_datetime),
        )

    def _candidate_types(self) -> set[str]:
        rows = self.conn.execute("SELECT candidate_type FROM duplicate_candidates").fetchall()
        return {str(r["candidate_type"]) for r in rows}

    def test_name_and_suffix_size_buckets_generate_distinct_candidates(self) -> None:
        self._insert_media("D:/A/IMG_0001.JPG", "D:/A", "IMG_0001.JPG", 900_000, "2024-01-01T00:00:00")
        self._insert_media("D:/B/IMG_0001.JPG", "D:/B", "IMG_0001.JPG", 900_000, "2024-01-01T00:00:00")
        self._insert_media("D:/C/RENAMED_A.JPG", "D:/C", "RENAMED_A.JPG", 900_000, "2024-01-01T00:00:00")
        self.conn.commit()

        summary = analyze_duplicates(self.conn, 1)
        self.assertGreater(summary["candidate_count"], 0)
        kinds = self._candidate_types()
        self.assertIn("probable_duplicate", kinds)
        self.assertIn("renamed_duplicate_candidate", kinds)

        rows = self.conn.execute("SELECT evidence_json FROM duplicate_candidates").fetchall()
        for row in rows:
            json.loads(str(row["evidence_json"]))

    def test_collision_derivative_and_folder_pair_hotspot_are_screening_candidates(self) -> None:
        for idx, size in enumerate((100_000, 200_000, 300_000), start=1):
            self._insert_media(f"D:/A/PAIR_{idx}.JPG", "D:/A", f"PAIR_{idx}.JPG", size)
            self._insert_media(f"D:/B/PAIR_{idx}.JPG", "D:/B", f"PAIR_{idx}.JPG", size)
        self._insert_media("D:/A/IMG_7777.JPG", "D:/A", "IMG_7777.JPG", 700_000)
        self._insert_media("D:/B/IMG_7777.JPG", "D:/B", "IMG_7777.JPG", 300_000)
        self._insert_media("D:/A/SHARE_1.JPG", "D:/A", "SHARE_1.JPG", 1_000_000)
        self._insert_media("D:/B/SHARE_1.JPG", "D:/B", "SHARE_1.JPG", 250_000)
        self.conn.commit()

        analyze_duplicates(self.conn, 1)
        kinds = self._candidate_types()
        self.assertIn("same_name_collision", kinds)
        self.assertIn("transferred_derivative", kinds)
        self.assertIn("folder_pair_burst", kinds)

        relation = self.conn.execute("SELECT * FROM folder_pair_relations").fetchone()
        self.assertIsNotNone(relation)
        self.assertGreaterEqual(int(relation["same_size_count"]), 3)

    def test_noisy_suffix_size_bucket_prevents_pair_explosion(self) -> None:
        for idx in range(250):
            self._insert_media(f"D:/cache/{idx}.jpg", "D:/cache", f"{idx}.jpg", 12_345)
        self.conn.commit()

        analyze_duplicates(self.conn, 1)
        kinds = self._candidate_types()
        self.assertIn("noisy_size_bucket", kinds)
        candidate_count = self.conn.execute("SELECT COUNT(*) AS c FROM duplicate_candidates").fetchone()["c"]
        self.assertLess(int(candidate_count), 10)

    def test_goal_tables_are_populated(self) -> None:
        self._insert_media("D:/A/IMG_1000.JPG", "D:/A", "IMG_1000.JPG", 800_000)
        self._insert_media("D:/B/IMG_1000.JPG", "D:/B", "IMG_1000.JPG", 800_000)
        self.conn.commit()

        analyze_duplicates(self.conn, 1)
        name_group_count = self.conn.execute("SELECT COUNT(*) AS c FROM name_groups").fetchone()["c"]
        member_count = self.conn.execute("SELECT COUNT(*) AS c FROM candidate_members").fetchone()["c"]
        self.assertGreater(int(name_group_count), 0)
        self.assertGreater(int(member_count), 0)


if __name__ == "__main__":
    unittest.main()
