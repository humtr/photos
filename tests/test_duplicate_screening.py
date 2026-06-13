from __future__ import annotations

import sys
import unittest
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from photos.database import connect
from photos.pairing import find_duplicate_candidate_buckets
from photo_organizer_app import PhotoLibraryEngine, PhotoRecord


class TestDuplicateScreening(unittest.TestCase):
    def test_add_fingerprints_bucketed_screening(self) -> None:
        # Create PhotoLibraryEngine
        on_progress = MagicMock()
        stop_event = threading.Event()
        engine = PhotoLibraryEngine(on_progress, stop_event)

        # 1. Unique file (unique name, unique size/suffix) -> should NOT compute hashes
        rec_unique = PhotoRecord(
            path="unique.jpg",
            size=100,
            created_at=0.0,
            modified_at=0.0,
            best_date=datetime.now(),
            date_source="file",
            place="",
        )

        # 2. Size/suffix duplicate candidate -> should compute hashes
        rec_dup_size1 = PhotoRecord(
            path="dup_size1.jpg",
            size=200,
            created_at=0.0,
            modified_at=0.0,
            best_date=datetime.now(),
            date_source="file",
            place="",
        )
        rec_dup_size2 = PhotoRecord(
            path="dup_size2.jpg",
            size=200,
            created_at=0.0,
            modified_at=0.0,
            best_date=datetime.now(),
            date_source="file",
            place="",
        )

        # 3. Name duplicate candidate -> should compute hashes
        rec_dup_name1 = PhotoRecord(
            path="sub1/dup_name.jpg",
            size=300,
            created_at=0.0,
            modified_at=0.0,
            best_date=datetime.now(),
            date_source="file",
            place="",
        )
        rec_dup_name2 = PhotoRecord(
            path="sub2/dup_name.jpg",
            size=400,
            created_at=0.0,
            modified_at=0.0,
            best_date=datetime.now(),
            date_source="file",
            place="",
        )

        records = [rec_unique, rec_dup_size1, rec_dup_size2, rec_dup_name1, rec_dup_name2]

        with patch("photo_organizer_app.sha256_file", return_value="dummy_sha") as mock_sha, \
             patch("photo_organizer_app.image_phash", return_value="dummy_phash") as mock_phash:

            result = engine.add_fingerprints(records)

            # Assert number of output records matches input
            self.assertEqual(len(result), 5)

            # Unique record should have original/empty sha256 and phash, and mock was not called for it
            self.assertEqual(result[0].sha256, "")
            self.assertEqual(result[0].phash, "")

            # Candidate records should have the mock returned hashes
            self.assertEqual(result[1].sha256, "dummy_sha")
            self.assertEqual(result[1].phash, "dummy_phash")
            self.assertEqual(result[2].sha256, "dummy_sha")
            self.assertEqual(result[2].phash, "dummy_phash")
            self.assertEqual(result[3].sha256, "dummy_sha")
            self.assertEqual(result[3].phash, "dummy_phash")
            self.assertEqual(result[4].sha256, "dummy_sha")
            self.assertEqual(result[4].phash, "dummy_phash")

            # Verify mocks were called only for candidate paths
            called_paths = {args[0] for args, _ in mock_sha.call_args_list}
            self.assertNotIn("unique.jpg", called_paths)
            self.assertIn("dup_size1.jpg", called_paths)
            self.assertIn("dup_size2.jpg", called_paths)
            self.assertIn("sub1/dup_name.jpg", called_paths)
            self.assertIn("sub2/dup_name.jpg", called_paths)

    def test_find_duplicate_candidate_buckets(self) -> None:
        con = connect(":memory:")
        try:
            # Insert standard media files
            # Bucket 1: ".jpg", size 500 (2 matches, both exists_on_disk = 1) -> Candidate!
            con.execute(
                """
                INSERT INTO media_files(root, path, rel_path, parent_key, name, stem_key, suffix, media_type, size_bytes, mtime_ns, exists_on_disk, indexed_at)
                VALUES('root', 'path/to/a.jpg', 'to/a.jpg', 'to', 'a.jpg', 'a', '.jpg', 'jpeg', 500, 12345, 1, 'indexed_at')
                """
            )
            con.execute(
                """
                INSERT INTO media_files(root, path, rel_path, parent_key, name, stem_key, suffix, media_type, size_bytes, mtime_ns, exists_on_disk, indexed_at)
                VALUES('root', 'path/to/b.jpg', 'to/b.jpg', 'to', 'b.jpg', 'b', '.jpg', 'jpeg', 500, 12345, 1, 'indexed_at')
                """
            )

            # Bucket 2: ".png", size 500 (1 match) -> NOT a candidate
            con.execute(
                """
                INSERT INTO media_files(root, path, rel_path, parent_key, name, stem_key, suffix, media_type, size_bytes, mtime_ns, exists_on_disk, indexed_at)
                VALUES('root', 'path/to/c.png', 'to/c.png', 'to', 'c.png', 'c', '.png', 'image', 500, 12345, 1, 'indexed_at')
                """
            )

            # Bucket 3: ".jpg", size 600 (2 records, but 1 exists_on_disk = 0) -> NOT a candidate
            con.execute(
                """
                INSERT INTO media_files(root, path, rel_path, parent_key, name, stem_key, suffix, media_type, size_bytes, mtime_ns, exists_on_disk, indexed_at)
                VALUES('root', 'path/to/d.jpg', 'to/d.jpg', 'to', 'd.jpg', 'd', '.jpg', 'jpeg', 600, 12345, 1, 'indexed_at')
                """
            )
            con.execute(
                """
                INSERT INTO media_files(root, path, rel_path, parent_key, name, stem_key, suffix, media_type, size_bytes, mtime_ns, exists_on_disk, indexed_at)
                VALUES('root', 'path/to/e.jpg', 'to/e.jpg', 'to', 'e.jpg', 'e', '.jpg', 'jpeg', 600, 12345, 0, 'indexed_at')
                """
            )

            con.commit()

            buckets = find_duplicate_candidate_buckets(con)

            # There should be exactly 1 candidate bucket
            self.assertEqual(len(buckets), 1)
            bucket = buckets[0]
            self.assertEqual(bucket["suffix"], ".jpg")
            self.assertEqual(bucket["size"], 500)
            self.assertEqual(len(bucket["members"]), 2)
            self.assertEqual(bucket["members"][0]["path"], "path/to/a.jpg")
            self.assertEqual(bucket["members"][1]["path"], "path/to/b.jpg")

        finally:
            con.close()

    def test_sqlite_caching_and_telemetry(self) -> None:
        import tempfile
        import shutil
        from unittest.mock import MagicMock, patch

        with tempfile.TemporaryDirectory() as tmpdir:
            on_progress = MagicMock()
            stop_event = threading.Event()
            engine = PhotoLibraryEngine(on_progress, stop_event, cache_dir=tmpdir)

            # Two files with same size and suffix -> candidates!
            rec_1 = PhotoRecord(
                path="dup1.jpg",
                size=500,
                created_at=0.0,
                modified_at=100.0,
                best_date=datetime.now(),
                date_source="file",
                place="",
            )
            rec_2 = PhotoRecord(
                path="dup2.jpg",
                size=500,
                created_at=0.0,
                modified_at=100.0,
                best_date=datetime.now(),
                date_source="file",
                place="",
            )

            records = [rec_1, rec_2]

            with patch("photo_organizer_app.sha256_file", return_value="sha_from_mock") as mock_sha, \
                 patch("photo_organizer_app.image_phash", return_value="phash_from_mock") as mock_phash:

                # First run - Cache Miss
                result1 = engine.add_fingerprints(records)
                self.assertEqual(len(result1), 2)
                self.assertEqual(result1[0].sha256, "sha_from_mock")
                self.assertEqual(result1[0].phash, "phash_from_mock")
                self.assertEqual(mock_sha.call_count, 2)
                self.assertEqual(mock_phash.call_count, 2)

                # Verify database file exists and table has data
                db_path = Path(tmpdir) / ".photos-data" / "photos_gui_cache.db"
                self.assertTrue(db_path.exists())

                import sqlite3
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()
                cursor.execute("SELECT path, sha256 FROM media_fingerprints")
                rows = cursor.fetchall()
                self.assertEqual(len(rows), 2)
                conn.close()

                # Reset mocks to verify Cache Hit
                mock_sha.reset_mock()
                mock_phash.reset_mock()

                # Second run - Cache Hit
                result2 = engine.add_fingerprints(records)
                self.assertEqual(len(result2), 2)
                self.assertEqual(result2[0].sha256, "sha_from_mock")
                self.assertEqual(result2[0].phash, "phash_from_mock")

                # Mocks should not be called since we hit the SQLite cache!
                self.assertEqual(mock_sha.call_count, 0)
                self.assertEqual(mock_phash.call_count, 0)


if __name__ == "__main__":
    unittest.main()
