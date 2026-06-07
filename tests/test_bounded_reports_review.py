from __future__ import annotations

import csv
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from photos.database import connect, utc_now
from photos.reports import build_management_report, write_management_report_page
from photos.review import export_review_package, review_queue_counts


def _media_row(
    index: int,
    *,
    path: str,
    parent: str,
    stem: str,
    media_type: str,
    sha256: str | None = None,
) -> tuple[object, ...]:
    now = utc_now()
    name = Path(path).name
    return (
        index,
        "C:/library",
        path,
        path,
        parent,
        name,
        stem,
        Path(name).suffix.lower(),
        media_type,
        1000 + index,
        index,
        sha256,
        now,
        1,
        None,
        now,
    )


def _populate(con) -> dict[str, int]:
    rows: list[tuple[object, ...]] = []
    index = 1
    for pair in range(120):
        parent = f"paired/{pair:03d}"
        stem = f"img_{pair:03d}"
        rows.append(
            _media_row(
                index,
                path=f"C:/library/{parent}/{stem}.ARW",
                parent=parent,
                stem=stem,
                media_type="raw",
            )
        )
        index += 1
        rows.append(
            _media_row(
                index,
                path=f"C:/library/{parent}/{stem}.JPG",
                parent=parent,
                stem=stem,
                media_type="jpeg",
            )
        )
        index += 1
    for raw in range(80):
        parent = f"raw-only/{raw:03d}"
        stem = f"raw_{raw:03d}"
        rows.append(
            _media_row(
                index,
                path=f"C:/library/{parent}/{stem}.RAF",
                parent=parent,
                stem=stem,
                media_type="raw",
            )
        )
        index += 1
    for screenshot in range(60):
        rows.append(
            _media_row(
                index,
                path=f"C:/library/screens/shot_{screenshot:03d}.PNG",
                parent="screens",
                stem=f"shot_{screenshot:03d}",
                media_type="screenshot",
            )
        )
        index += 1
    classified_paths: list[str] = []
    for classified in range(40):
        path = f"C:/library/photos/object_{classified:03d}.JPG"
        classified_paths.append(path)
        rows.append(
            _media_row(
                index,
                path=path,
                parent="photos",
                stem=f"object_{classified:03d}",
                media_type="photo",
            )
        )
        index += 1
    for video in range(30):
        path = f"C:/library/videos/video_{video:03d}.MP4"
        if video == 0:
            path = "=unsafe-video.MP4"
        rows.append(
            _media_row(
                index,
                path=path,
                parent="videos",
                stem=f"video_{video:03d}",
                media_type="video",
            )
        )
        index += 1
    for duplicate in range(2):
        rows.append(
            _media_row(
                index,
                path=f"C:/library/duplicates/copy_{duplicate}.JPG",
                parent="duplicates",
                stem=f"copy_{duplicate}",
                media_type="jpeg",
                sha256="same-content",
            )
        )
        index += 1

    con.executemany(
        """
        INSERT INTO media_files(
            id, root, path, rel_path, parent_key, name, stem_key, suffix, media_type,
            size_bytes, mtime_ns, sha256, indexed_at, exists_on_disk, missing_at, last_seen_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    now = utc_now()
    con.executemany(
        """
        INSERT INTO classification_results(path, label, confidence, model, details_json, updated_at)
        VALUES(?, 'object', 0.9, 'synthetic', '{}', ?)
        """,
        [(path, now) for path in classified_paths],
    )
    con.commit()
    return {
        "raw_jpg_pairs": 120,
        "raw_without_jpg": 80,
        "non_person_candidates": 100,
        "videos": 30,
        "exact_duplicate_groups": 1,
    }


class BoundedReportReviewTests(unittest.TestCase):
    def test_report_detail_pages_are_bounded_with_exact_totals(self) -> None:
        with closing(connect(":memory:")) as con, tempfile.TemporaryDirectory() as tmp:
            expected = _populate(con)
            report = build_management_report(con, max_detail_items=7)

            self.assertEqual(len(report["raw_pairs"]), 7)
            self.assertEqual(len(report["raw_without_jpg"]), 7)
            self.assertEqual(len(report["non_person_candidates"]), 7)
            self.assertEqual(report["detail_limits"]["raw_pairs_total"], expected["raw_jpg_pairs"])
            self.assertEqual(
                report["detail_limits"]["raw_without_jpg_total"], expected["raw_without_jpg"]
            )
            self.assertEqual(
                report["detail_limits"]["non_person_candidates_total"],
                expected["non_person_candidates"],
            )

            for section, total in (
                ("raw_pairs", expected["raw_jpg_pairs"]),
                ("raw_without_jpg", expected["raw_without_jpg"]),
                ("non_person_candidates", expected["non_person_candidates"]),
            ):
                page = write_management_report_page(
                    con,
                    Path(tmp) / f"{section}.json",
                    section=section,
                    page=3,
                    page_size=11,
                )
                self.assertEqual(page["total_items"], total)
                self.assertEqual(len(page["items"]), 11)

    def test_review_counts_and_export_artifacts_preserve_streamed_rows(self) -> None:
        with closing(connect(":memory:")) as con, tempfile.TemporaryDirectory() as tmp:
            expected = _populate(con)
            self.assertEqual(review_queue_counts(con), expected)

            with mock.patch(
                "photos.review.build_review_queues",
                side_effect=AssertionError("export must not materialize all review queues"),
            ):
                summary = export_review_package(con, tmp, max_shortcuts_per_queue=0)

            expected_export_counts = {
                "exact_duplicates": 2,
                "raw_jpg_pairs": 120,
                "raw_without_jpg": 80,
                "non_person_candidates": 100,
                "videos": 30,
            }
            self.assertEqual(summary["queue_counts"], expected_export_counts)

            output = Path(tmp)
            with (output / "decisions_template.csv").open(newline="", encoding="utf-8") as handle:
                decisions = list(csv.DictReader(handle))
            self.assertEqual(len(decisions), sum(expected_export_counts.values()))
            self.assertTrue(any(row["path"] == "'=unsafe-video.MP4" for row in decisions))
            for queue, count in expected_export_counts.items():
                with (output / "queues" / f"{queue}.csv").open(newline="", encoding="utf-8") as handle:
                    self.assertEqual(len(list(csv.DictReader(handle))), count)


if __name__ == "__main__":
    unittest.main()
