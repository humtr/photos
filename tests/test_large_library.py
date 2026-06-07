from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from photos.database import utc_now
from photos.reports import write_management_report_page
from photos.services import PhotoOrganizerService


DEFAULT_SYNTHETIC_ROWS = 12_000
ENV_SYNTHETIC_ROWS = "PHOTOS_LARGE_LIBRARY_ROWS"
INSERT_CHUNK_SIZE = 5_000
DUPLICATE_GROUPS = 100


def configured_row_count() -> int:
    value = int(os.environ.get(ENV_SYNTHETIC_ROWS, DEFAULT_SYNTHETIC_ROWS))
    if value < DUPLICATE_GROUPS * 2:
        raise ValueError(f"{ENV_SYNTHETIC_ROWS} must be at least {DUPLICATE_GROUPS * 2}")
    return value


def _chunks(rows, size: int = INSERT_CHUNK_SIZE):
    chunk = []
    for row in rows:
        chunk.append(row)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def populate_synthetic_library(service: PhotoOrganizerService, row_count: int) -> tuple[int, int]:
    """Populate public-schema rows efficiently without creating physical media files."""

    con = service.con
    now = utc_now()
    con.execute("BEGIN")
    for chunk in _chunks(
        (
            (
                index,
                "C:/Synthetic/Library",
                f"C:/Synthetic/Library/folder-{index % 1000:04d}/IMG_{index:07d}.JPG",
                f"folder-{index % 1000:04d}/IMG_{index:07d}.JPG",
                f"folder-{index % 1000:04d}",
                f"IMG_{index:07d}.JPG",
                f"img_{index:07d}",
                ".jpg",
                "photo",
                1024 + index,
                1_700_000_000_000_000_000 + index,
                f"duplicate-{(index - 1) // 2:04d}" if index <= DUPLICATE_GROUPS * 2 else None,
                now,
                1,
                None,
                now,
            )
            for index in range(1, row_count + 1)
        )
    ):
        con.executemany(
            """
            INSERT INTO media_files(
                id, root, path, rel_path, parent_key, name, stem_key, suffix, media_type,
                size_bytes, mtime_ns, sha256, indexed_at, exists_on_disk, missing_at, last_seen_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            chunk,
        )

    plan_id = int(
        con.execute(
            """
            INSERT INTO organize_plans(strategy, archive_root, status, created_at, summary_json)
            VALUES('synthetic_scale', 'D:/Synthetic/Archive', 'draft', ?, '{}')
            """,
            (now,),
        ).lastrowid
    )
    for chunk in _chunks(
        (
            (
                index,
                plan_id,
                f"C:/Synthetic/Library/folder-{index % 1000:04d}/IMG_{index:07d}.JPG",
                f"D:/Synthetic/Archive/folder-{index % 1000:04d}/IMG_{index:07d}.JPG",
                "archive_move",
                1024 + index,
                1_700_000_000_000_000_000 + index,
                "pending",
                "{}",
            )
            for index in range(1, row_count + 1)
        )
    ):
        con.executemany(
            """
            INSERT INTO plan_actions(
                id, plan_id, source_path, destination_path, action_type,
                expected_size, expected_mtime_ns, status, reason_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            chunk,
        )

    batch_id = int(
        con.execute(
            """
            INSERT INTO execution_batches(
                plan_id, transfer_method, estimated_bytes, status, started_at, summary_json
            )
            VALUES(?, 'synthetic_no_mutation', 0, 'planned', ?, '{}')
            """,
            (plan_id, now),
        ).lastrowid
    )
    for chunk in _chunks(
        (
            (
                index,
                batch_id,
                index,
                f"C:/Synthetic/Library/folder-{index % 1000:04d}/IMG_{index:07d}.JPG",
                f"D:/Synthetic/Archive/folder-{index % 1000:04d}/IMG_{index:07d}.JPG",
                "pending",
            )
            for index in range(1, row_count + 1)
        )
    ):
        con.executemany(
            """
            INSERT INTO batch_items(
                id, batch_id, plan_action_id, source_path, destination_path, status
            )
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            chunk,
        )
    con.commit()
    return plan_id, batch_id


class LargeLibrarySyntheticTests(unittest.TestCase):
    def test_public_paging_and_report_surfaces_at_configured_scale(self) -> None:
        row_count = configured_row_count()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with PhotoOrganizerService(base / "large-library.sqlite") as service:
                plan_id, batch_id = populate_synthetic_library(service, row_count)

                media = service.list_media(page=3, page_size=137)
                self.assertTrue(media["ok"], media)
                self.assertEqual(media["data"]["total"], row_count)
                self.assertEqual(len(media["data"]["rows"]), 137)
                self.assertLessEqual(len(media["data"]["rows"]), media["data"]["page_size"])
                self.assertTrue(media["data"]["has_next"])

                report = service.management_report(top_folders=7)
                self.assertTrue(report["ok"], report)
                self.assertEqual(report["data"]["inventory"]["total_files"], row_count)
                self.assertLessEqual(len(report["data"]["inventory"]["top_folders"]), 7)
                self.assertEqual(report["data"]["detail_limits"]["duplicate_groups_total"], DUPLICATE_GROUPS)

                detail = write_management_report_page(
                    service.con,
                    base / "duplicate-page.json",
                    section="duplicates",
                    page=1,
                    page_size=13,
                )
                self.assertEqual(detail["total_items"], DUPLICATE_GROUPS)
                self.assertEqual(len(detail["items"]), 13)
                self.assertLessEqual(len(detail["items"]), detail["page_size"])

                actions = service.list_plan_actions(plan_id, limit=211, offset=211)
                self.assertTrue(actions["ok"], actions)
                self.assertEqual(actions["data"]["total"], row_count)
                self.assertEqual(len(actions["data"]["rows"]), 211)

                items = service.list_batch_items(batch_id, limit=223, offset=223)
                self.assertTrue(items["ok"], items)
                self.assertEqual(items["data"]["total"], row_count)
                self.assertEqual(len(items["data"]["rows"]), 223)

                batches = service.list_execution_batches(plan_id=plan_id, limit=1)
                self.assertTrue(batches["ok"], batches)
                self.assertEqual(batches["data"]["total"], 1)
                self.assertEqual(len(batches["data"]["rows"]), 1)
                self.assertEqual(batches["data"]["rows"][0]["item_count"], row_count)


if __name__ == "__main__":
    unittest.main()
