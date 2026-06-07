from __future__ import annotations

import json
import unittest
from unittest import mock

from photos.database import utc_now
from photos.date_audit import (
    MAX_DATE_AUDIT_ITEMS_PER_GROUP,
    list_date_audits,
    refresh_date_audit,
)
from photos.duplicates import (
    MAX_EVIDENCE_SIZE_VARIANTS,
    MAX_SCREENING_BUCKET_MEMBERS,
    refresh_duplicate_candidates,
)
from photos.hashing import (
    duplicate_group_count,
    duplicate_groups,
    duplicate_groups_page,
    iter_duplicate_group_members,
    iter_duplicate_hash_groups,
)
from photos.store import PhotoStore


def _insert_media(
    store: PhotoStore,
    *,
    row_id: int,
    path: str,
    parent: str,
    name: str,
    size: int,
    sha256: str | None,
    mtime_ns: int = 1_704_067_200_000_000_000,
) -> None:
    now = utc_now()
    store.con.execute(
        """
        INSERT INTO media_files(
            id, root, path, rel_path, parent_key, name, stem_key, suffix, media_type,
            size_bytes, mtime_ns, sha256, indexed_at, exists_on_disk, missing_at, last_seen_at
        )
        VALUES(?, 'C:/library', ?, ?, ?, ?, ?, '.jpg', 'photo',
               ?, ?, ?, ?, 1, NULL, ?)
        """,
        (
            row_id,
            path,
            path,
            parent,
            name,
            name.removesuffix(".JPG").lower(),
            size,
            mtime_ns,
            sha256,
            now,
            now,
        ),
    )


class BoundedDuplicateDateAuditTests(unittest.TestCase):
    def test_duplicate_hash_metadata_pages_and_legacy_api_stay_compatible(self) -> None:
        with PhotoStore(":memory:") as store:
            for index in range(6):
                _insert_media(
                    store,
                    row_id=index + 1,
                    path=f"C:/library/group-{index // 2}/item-{index}.JPG",
                    parent=f"group-{index // 2}",
                    name=f"item-{index}.JPG",
                    size=100 + index // 2,
                    sha256=f"hash-{index // 2}",
                )

            self.assertEqual(duplicate_group_count(store.con), 3)
            metadata = list(iter_duplicate_hash_groups(store.con, limit=2, offset=1))
            self.assertEqual([row["sha256"] for row in metadata], ["hash-1", "hash-2"])
            self.assertEqual([row["member_count"] for row in metadata], [2, 2])
            self.assertEqual(
                len(list(iter_duplicate_group_members(store.con, "hash-0", limit=1))),
                1,
            )

            page, total = duplicate_groups_page(store.con, page=1, page_size=2)
            self.assertEqual(total, 3)
            self.assertEqual(len(page), 1)
            self.assertEqual(len(duplicate_groups(store.con)), 3)

    def test_candidate_refresh_streams_exact_groups_and_caps_screening_evidence(self) -> None:
        with PhotoStore(":memory:") as store:
            row_id = 1
            for index in range(210):
                _insert_media(
                    store,
                    row_id=row_id,
                    path=f"C:/library/exact-{index:03d}/exact-{index:03d}.JPG",
                    parent=f"exact-{index:03d}",
                    name=f"exact-{index:03d}.JPG",
                    size=4096,
                    sha256="exact-hash",
                )
                row_id += 1
            for index in range(250):
                _insert_media(
                    store,
                    row_id=row_id,
                    path=f"C:/library/name-{index:03d}/COLLIDE.JPG",
                    parent=f"name-{index:03d}",
                    name="COLLIDE.JPG",
                    size=100_000 + index,
                    sha256=None,
                )
                row_id += 1
            for index, name in enumerate(("Ä.JPG", "ä.jpg")):
                _insert_media(
                    store,
                    row_id=row_id,
                    path=f"C:/library/unicode-{index}/{name}",
                    parent=f"unicode-{index}",
                    name=name,
                    size=200_000 + index,
                    sha256=None,
                )
                row_id += 1

            with mock.patch(
                "photos.hashing.duplicate_groups",
                side_effect=AssertionError("legacy duplicate_groups must not be used"),
            ), mock.patch(
                "photos.pairing.find_duplicate_candidate_buckets",
                side_effect=AssertionError("legacy size buckets must not be used"),
            ):
                result = refresh_duplicate_candidates(store.con)

            self.assertEqual(result["candidate_count"], 3)
            self.assertIsNotNone(
                store.con.execute(
                    "SELECT id FROM duplicate_candidates WHERE candidate_key = ?",
                    ("name:ä.jpg",),
                ).fetchone()
            )
            exact = store.con.execute(
                "SELECT id, evidence_json FROM duplicate_candidates WHERE candidate_key = ?",
                ("exact:exact-hash",),
            ).fetchone()
            self.assertEqual(json.loads(exact["evidence_json"])["member_count"], 210)
            self.assertEqual(
                store.con.execute(
                    "SELECT COUNT(*) AS count FROM candidate_members WHERE candidate_id = ?",
                    (exact["id"],),
                ).fetchone()["count"],
                210,
            )

            name = store.con.execute(
                "SELECT id, evidence_json FROM duplicate_candidates WHERE candidate_key = ?",
                ("name:collide.jpg",),
            ).fetchone()
            evidence = json.loads(name["evidence_json"])
            self.assertEqual(evidence["member_count"], 250)
            self.assertEqual(evidence["size_variant_count"], 250)
            self.assertEqual(len(evidence["size_variants"]), MAX_EVIDENCE_SIZE_VARIANTS)
            self.assertTrue(evidence["size_variants_truncated"])
            self.assertEqual(
                store.con.execute(
                    "SELECT COUNT(*) AS count FROM candidate_members WHERE candidate_id = ?",
                    (name["id"],),
                ).fetchone()["count"],
                MAX_SCREENING_BUCKET_MEMBERS,
            )

    def test_date_audit_refresh_streams_items_and_listing_bounds_each_group(self) -> None:
        with PhotoStore(":memory:") as store:
            row_id = 1
            for folder in range(3):
                parent = f"trip-2022-{folder:02d}"
                for index in range(260):
                    _insert_media(
                        store,
                        row_id=row_id,
                        path=f"C:/library/{parent}/20190101-{index:03d}.JPG",
                        parent=parent,
                        name=f"20190101-{index:03d}.JPG",
                        size=1000 + index,
                        sha256=None,
                    )
                    row_id += 1

            result = refresh_date_audit(store.con)
            self.assertEqual(result, {"group_count": 3, "item_count": 780})
            evidence = [
                json.loads(row["evidence_json"])["item_count"]
                for row in store.con.execute("SELECT evidence_json FROM date_audit_groups")
            ]
            self.assertEqual(evidence, [260, 260, 260])

            first_page = list_date_audits(store.con, limit=2, item_limit=7)
            self.assertEqual(first_page["total"], 3)
            self.assertEqual(len(first_page["rows"]), 2)
            self.assertTrue(all(len(row["items"]) == 7 for row in first_page["rows"]))

            capped = list_date_audits(store.con, limit=1, item_limit=10_000)
            self.assertEqual(len(capped["rows"][0]["items"]), MAX_DATE_AUDIT_ITEMS_PER_GROUP)


if __name__ == "__main__":
    unittest.main()
