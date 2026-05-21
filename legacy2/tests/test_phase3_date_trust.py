from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
import shutil
import unittest
import uuid

from photos.metadata_audit import audit_dates
from photos.planning import build_plan
from photos.store import Store


def _ns_for_date(value: str) -> int:
    return int(datetime.fromisoformat(f"{value}T12:00:00+00:00").timestamp() * 1_000_000_000)


class TestPhase3DateTrust(unittest.TestCase):
    def _workdir(self) -> Path:
        root = Path.cwd() / ".test-tmp" / f"phase3-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def _store(self, root: Path) -> tuple[Store, int, Path, Path]:
        source_root = root / "source"
        archive_root = root / "archive"
        source_root.mkdir()
        archive_root.mkdir()
        store = Store(root / "photos.sqlite")
        store.init_schema()
        scan_root_id = store.add_scan_root(str(source_root), str(archive_root))
        self.addCleanup(store.close)
        return store, scan_root_id, source_root, archive_root

    def _add_media(
        self,
        store: Store,
        scan_root_id: int,
        source_root: Path,
        relative_path: str,
        *,
        exif: str | None,
        filesystem_date: str,
        ctime_date: str | None = None,
        gps: tuple[float, float] | None = None,
    ) -> Path:
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"photo")
        ns = _ns_for_date(filesystem_date)
        os.utime(path, ns=(ns, ns))
        store.add_media_file(scan_root_id, path)
        store.conn.execute(
            "UPDATE media_files SET exif_datetime=?, ctime_ns=?, gps_lat=?, gps_lon=? WHERE path=?",
            (
                exif,
                _ns_for_date(ctime_date or filesystem_date),
                gps[0] if gps else None,
                gps[1] if gps else None,
                str(path),
            ),
        )
        store.conn.commit()
        return path

    def _groups(self, store: Store) -> dict[str, dict]:
        rows = store.conn.execute("SELECT issue_type, evidence_json FROM date_audit_groups").fetchall()
        return {str(row["issue_type"]): json.loads(str(row["evidence_json"])) for row in rows}

    def test_exif_conflict_with_folder_date_routes_to_review(self) -> None:
        root = self._workdir()
        store, scan_root_id, source_root, _ = self._store(root)
        self._add_media(
            store,
            scan_root_id,
            source_root,
            "2020-05-trip/IMG_20200504.jpg",
            exif="2012-01-02T08:00:00",
            filesystem_date="2020-05-04",
            ctime_date="2024-12-31",
            gps=(37.5665, 126.9780),
        )
        folder = str(source_root / "2020-05-trip")
        store.conn.execute(
            """
            INSERT INTO folder_places(scan_root_id,folder_path,dominant_place,sample_count,updated_at)
            VALUES(?,?,?,?,?)
            """,
            (scan_root_id, folder, "Seoul, South Korea", 1, "2026-05-21T00:00:00Z"),
        )
        store.conn.commit()

        summary = audit_dates(store.conn, scan_root_id)

        groups = self._groups(store)
        self.assertGreaterEqual(summary["issue_count"], 1)
        self.assertIn("folder_date_conflict", groups)
        self.assertIn("exif_untrusted_cluster", groups)
        self.assertEqual(groups["exif_untrusted_cluster"]["proposed_canonical_date"], "2020-05-01")
        self.assertEqual(groups["exif_untrusted_cluster"]["dominant_filesystem_mtime"], "2020-05-04")
        self.assertEqual(groups["exif_untrusted_cluster"]["dominant_filesystem_ctime"], "2024-12-31")
        self.assertEqual(groups["exif_untrusted_cluster"]["sequence_date_range"]["start"], "2020-05-04")
        self.assertEqual(groups["exif_untrusted_cluster"]["folder_place"]["dominant_place"], "Seoul, South Korea")
        self.assertEqual(groups["exif_untrusted_cluster"]["gps_context"]["gps_file_count"], 1)
        suggestion = store.conn.execute("SELECT proposed_value, status FROM metadata_edit_suggestions").fetchone()
        self.assertEqual(str(suggestion["proposed_value"]), "2020-05-01")
        self.assertEqual(str(suggestion["status"]), "pending_approval")

    def test_filesystem_backup_copy_date_is_suspected(self) -> None:
        root = self._workdir()
        store, scan_root_id, source_root, _ = self._store(root)
        self._add_media(
            store,
            scan_root_id,
            source_root,
            "2020-05-trip/IMG_20200504.jpg",
            exif="2020-05-04T08:00:00",
            filesystem_date="2024-12-31",
            ctime_date="2025-01-01",
        )

        audit_dates(store.conn, scan_root_id)

        groups = self._groups(store)
        self.assertIn("filesystem_backup_date_suspected", groups)
        self.assertEqual(groups["filesystem_backup_date_suspected"]["dominant_filesystem"], "2024-12-31")
        self.assertEqual(groups["filesystem_backup_date_suspected"]["dominant_filesystem_ctime"], "2025-01-01")
        self.assertEqual(groups["filesystem_backup_date_suspected"]["proposed_canonical_date"], "2020-05-01")

    def test_neighboring_sequence_date_range_is_recorded_in_evidence(self) -> None:
        root = self._workdir()
        store, scan_root_id, source_root, _ = self._store(root)
        self._add_media(
            store,
            scan_root_id,
            source_root,
            "loose/IMG_20210322.jpg",
            exif=None,
            filesystem_date="2025-01-01",
        )
        self._add_media(
            store,
            scan_root_id,
            source_root,
            "loose/IMG_20210323.jpg",
            exif=None,
            filesystem_date="2025-01-01",
        )

        audit_dates(store.conn, scan_root_id)

        groups = self._groups(store)
        self.assertEqual(
            groups["missing_exif_cluster"]["sequence_date_range"],
            {"start": "2021-03-22", "end": "2021-03-23", "count": 2, "unique_count": 2},
        )

    def test_filename_date_is_stronger_than_missing_exif(self) -> None:
        root = self._workdir()
        store, scan_root_id, source_root, _ = self._store(root)
        path = self._add_media(
            store,
            scan_root_id,
            source_root,
            "loose/IMG_20210322.jpg",
            exif=None,
            filesystem_date="2025-01-01",
        )

        audit_dates(store.conn, scan_root_id)

        groups = self._groups(store)
        self.assertIn("missing_exif_cluster", groups)
        item = store.conn.execute(
            "SELECT filename_date, exif_date, proposed_canonical_date FROM date_audit_items WHERE path=?",
            (str(path),),
        ).fetchone()
        self.assertEqual(str(item["filename_date"]), "2021-03-22")
        self.assertIsNone(item["exif_date"])
        self.assertEqual(str(item["proposed_canonical_date"]), "2021-03-22")

    def test_approved_metadata_override_changes_plan_destination_without_editing_original_metadata(self) -> None:
        root = self._workdir()
        store, scan_root_id, source_root, archive_root = self._store(root)
        path = self._add_media(
            store,
            scan_root_id,
            source_root,
            "1999-backup/IMG_20200504.jpg",
            exif="1999-01-01T08:00:00",
            filesystem_date="2024-12-31",
        )
        original_exif = store.conn.execute("SELECT exif_datetime FROM media_files WHERE path=?", (str(path),)).fetchone()[
            "exif_datetime"
        ]
        store.conn.execute(
            """
            INSERT INTO metadata_edit_suggestions(target_type,target_path,proposed_value,source,status,reason_json)
            VALUES(?,?,?,?,?,?)
            """,
            ("media_file", str(path), "2020-05-04", "test_user_review", "approved", "{}"),
        )
        store.conn.commit()

        plan_id = build_plan(store, scan_root_id)

        action = store.list_plan_actions(plan_id)[0]
        self.assertEqual(Path(str(action["destination_path"])), archive_root / "2020-05-04" / "IMG_20200504.jpg")
        self.assertEqual(json.loads(str(action["reason_json"]))["reason"], "metadata_override")
        after_exif = store.conn.execute("SELECT exif_datetime FROM media_files WHERE path=?", (str(path),)).fetchone()[
            "exif_datetime"
        ]
        self.assertEqual(after_exif, original_exif)


if __name__ == "__main__":
    unittest.main()
