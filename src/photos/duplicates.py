from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Iterable

from .schemas import utc_now_iso
from .utils import json_dumps, parse_iso_date

MIN_SIZE_BUCKET_BYTES = 64 * 1024
NOISY_BUCKET_MEMBER_LIMIT = 200
FOLDER_PAIR_BURST_THRESHOLD = 3


def analyze_duplicates(conn: sqlite3.Connection, scan_root_id: int) -> dict:
    _clear_previous(conn, scan_root_id)
    _build_name_groups(conn, scan_root_id)

    rows = conn.execute(
        """
        SELECT path,folder_path,name,stem,suffix,size_bytes,mtime_ns,exif_datetime
        FROM media_files
        WHERE scan_root_id=? AND existence_state='seen'
        """,
        (scan_root_id,),
    ).fetchall()

    by_name: dict[str, list[sqlite3.Row]] = defaultdict(list)
    by_stem: dict[str, list[sqlite3.Row]] = defaultdict(list)
    by_suffix_size: dict[tuple[str, int], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_name[str(row["name"]).lower()].append(row)
        by_stem[str(row["stem"]).lower()].append(row)
        by_suffix_size[(str(row["suffix"]).lower(), int(row["size_bytes"]))].append(row)

    pair_stats: dict[tuple[str, str], dict] = {}
    inserted = 0
    inserted += _detect_name_buckets(conn, scan_root_id, by_name, pair_stats)
    inserted += _detect_suffix_size_buckets(conn, scan_root_id, by_suffix_size, pair_stats)
    inserted += _detect_transferred_derivatives(conn, scan_root_id, by_stem, pair_stats)
    inserted += _insert_folder_pair_bursts(conn, scan_root_id, pair_stats)
    conn.commit()
    return {"candidate_count": inserted}


def _clear_previous(conn: sqlite3.Connection, scan_root_id: int) -> None:
    ids = [int(r["id"]) for r in conn.execute("SELECT id FROM duplicate_candidates WHERE scan_root_id=?", (scan_root_id,))]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM candidate_members WHERE candidate_id IN ({placeholders})", ids)
    conn.execute("DELETE FROM duplicate_candidates WHERE scan_root_id=?", (scan_root_id,))
    conn.execute("DELETE FROM name_groups")
    conn.execute("DELETE FROM folder_pair_relations")


def _build_name_groups(conn: sqlite3.Connection, scan_root_id: int) -> None:
    conn.execute(
        """
        INSERT INTO name_groups(normalized_name, member_count, size_variants, date_range_json, status)
        SELECT lower(name), COUNT(*), COUNT(DISTINCT size_bytes), '{}', 'open'
        FROM media_files
        WHERE scan_root_id=? AND existence_state='seen'
        GROUP BY lower(name)
        HAVING COUNT(*) > 1
        """,
        (scan_root_id,),
    )


def _insert_candidate(
    conn: sqlite3.Connection,
    scan_root_id: int,
    key: str,
    kind: str,
    members: Iterable[sqlite3.Row],
    evidence: dict,
    confidence: float,
    recommended_action: str,
) -> int:
    member_rows = list(members)
    if not member_rows:
        raise ValueError("candidate requires at least one member")
    left = str(member_rows[0]["path"])
    right = str(member_rows[1]["path"]) if len(member_rows) > 1 else left
    evidence_json = json_dumps(evidence)
    cur = conn.execute(
        """
        INSERT INTO duplicate_candidates(
            scan_root_id,candidate_key,candidate_type,left_path,right_path,evidence_json,status,created_at,
            group_type,confidence,recommended_action,reason_json
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            scan_root_id,
            key,
            kind,
            left,
            right,
            evidence_json,
            "pending_review",
            utc_now_iso(),
            kind,
            confidence,
            recommended_action,
            evidence_json,
        ),
    )
    candidate_id = int(cur.lastrowid)
    for idx, row in enumerate(member_rows):
        conn.execute(
            """
            INSERT INTO candidate_members(candidate_id, path, member_role, evidence_json)
            VALUES(?,?,?,?)
            """,
            (
                candidate_id,
                str(row["path"]),
                "primary" if idx == 0 else "peer",
                evidence_json,
            ),
        )
    return candidate_id


def _track_pair(pair_stats: dict[tuple[str, str], dict], rows: Iterable[sqlite3.Row], kind: str) -> None:
    grouped = list(rows)
    if len(grouped) < 2:
        return
    folders = sorted({str(r["folder_path"]) for r in grouped})
    if len(folders) < 2:
        return
    for i in range(len(folders) - 1):
        for j in range(i + 1, len(folders)):
            pair = (folders[i], folders[j])
            stat = pair_stats.setdefault(
                pair,
                {
                    "matched_name_count": 0,
                    "same_size_count": 0,
                    "same_exif_count": 0,
                    "derivative_count": 0,
                    "collision_count": 0,
                    "sample_rows": grouped[:2],
                },
            )
            if kind in {"probable_duplicate", "renamed_duplicate_candidate"}:
                stat["same_size_count"] += 1
            if kind == "transferred_derivative":
                stat["derivative_count"] += 1
            if kind == "same_name_collision":
                stat["collision_count"] += 1
            stat["matched_name_count"] += 1


def _detect_name_buckets(
    conn: sqlite3.Connection,
    scan_root_id: int,
    by_name: dict[str, list[sqlite3.Row]],
    pair_stats: dict[tuple[str, str], dict],
) -> int:
    count = 0
    for name, group in by_name.items():
        if len(group) < 2:
            continue
        by_size: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for row in group:
            by_size[int(row["size_bytes"])].append(row)

        if len(by_size) > 1:
            reps = [rows[0] for _, rows in sorted(by_size.items())]
            evidence = {
                "screening_trigger": "camera_filename_iteration",
                "name": name,
                "size_variants": sorted(by_size.keys()),
                "member_count": len(group),
            }
            _insert_candidate(conn, scan_root_id, f"snc:{name}", "same_name_collision", reps[:2], evidence, 0.80, "keep_separate")
            _track_pair(pair_stats, reps[:2], "same_name_collision")
            count += 1

        for size, rows in by_size.items():
            if len(rows) < 2:
                continue
            dates = [parse_iso_date(str(r["exif_datetime"])) for r in rows if r["exif_datetime"]]
            dates = [d for d in dates if d]
            confidence = 0.82 if dates and len(set(dates)) == 1 else 0.72
            evidence = {
                "bucket": "name_bucket",
                "name": name,
                "size_bytes": size,
                "member_count": len(rows),
                "exif_dates": sorted(set(dates)),
            }
            _insert_candidate(conn, scan_root_id, f"pd:{name}:{size}", "probable_duplicate", rows[:10], evidence, confidence, "review_cleanup")
            _track_pair(pair_stats, rows, "probable_duplicate")
            count += 1
    return count


def _detect_suffix_size_buckets(
    conn: sqlite3.Connection,
    scan_root_id: int,
    by_suffix_size: dict[tuple[str, int], list[sqlite3.Row]],
    pair_stats: dict[tuple[str, str], dict],
) -> int:
    count = 0
    for (suffix, size), rows in by_suffix_size.items():
        if len(rows) < 2:
            continue
        names = {str(r["name"]).lower() for r in rows}
        if len(names) < 2:
            continue
        if size < MIN_SIZE_BUCKET_BYTES or len(rows) > NOISY_BUCKET_MEMBER_LIMIT:
            evidence = {
                "bucket": "suffix_size_bucket",
                "suffix": suffix,
                "size_bytes": size,
                "member_count": len(rows),
                "reason": "tiny_or_noisy_bucket",
            }
            _insert_candidate(conn, scan_root_id, f"noisy:{suffix}:{size}", "noisy_size_bucket", rows[:10], evidence, 0.35, "requires_review")
            count += 1
            continue
        evidence = {
            "bucket": "suffix_size_bucket",
            "suffix": suffix,
            "size_bytes": size,
            "member_count": len(rows),
            "distinct_names": sorted(names)[:20],
        }
        _insert_candidate(
            conn,
            scan_root_id,
            f"rss:{suffix}:{size}",
            "renamed_duplicate_candidate",
            rows[:20],
            evidence,
            0.68,
            "review_possible_rename_or_cleanup",
        )
        _track_pair(pair_stats, rows, "renamed_duplicate_candidate")
        count += 1
    return count


def _detect_transferred_derivatives(
    conn: sqlite3.Connection,
    scan_root_id: int,
    by_stem: dict[str, list[sqlite3.Row]],
    pair_stats: dict[tuple[str, str], dict],
) -> int:
    count = 0
    for stem, group in by_stem.items():
        if len(group) < 2:
            continue
        sizes = sorted({int(r["size_bytes"]) for r in group})
        if len(sizes) < 2:
            continue
        smallest, largest = sizes[0], sizes[-1]
        if largest <= 0 or smallest >= largest:
            continue
        ratio = smallest / largest
        if not 0.10 <= ratio <= 0.95:
            continue
        rows = sorted(group, key=lambda r: int(r["size_bytes"]))
        evidence = {
            "screening_trigger": "transfer_derivative_hotspot",
            "stem": stem,
            "smallest_size": smallest,
            "largest_size": largest,
            "ratio": round(ratio, 4),
            "member_count": len(rows),
        }
        _insert_candidate(
            conn,
            scan_root_id,
            f"td:{stem}",
            "transferred_derivative",
            [rows[0], rows[-1]],
            evidence,
            0.62,
            "review_derivative_cleanup",
        )
        _track_pair(pair_stats, [rows[0], rows[-1]], "transferred_derivative")
        count += 1
    return count


def _insert_folder_pair_bursts(conn: sqlite3.Connection, scan_root_id: int, pair_stats: dict[tuple[str, str], dict]) -> int:
    count = 0
    for (folder_a, folder_b), stat in pair_stats.items():
        total_signal = int(stat["same_size_count"]) + int(stat["derivative_count"]) + int(stat["collision_count"])
        if total_signal < FOLDER_PAIR_BURST_THRESHOLD:
            continue
        reason = {
            "screening_trigger": "folder_pair_hotspot",
            "folder_a": folder_a,
            "folder_b": folder_b,
            "matched_name_count": int(stat["matched_name_count"]),
            "same_size_count": int(stat["same_size_count"]),
            "derivative_count": int(stat["derivative_count"]),
            "collision_count": int(stat["collision_count"]),
        }
        conn.execute(
            """
            INSERT INTO folder_pair_relations(
                folder_a, folder_b, matched_name_count, same_size_count, same_exif_count,
                derivative_count, collision_count, dominant_place, date_range_json, confidence, reason_json
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                folder_a,
                folder_b,
                int(stat["matched_name_count"]),
                int(stat["same_size_count"]),
                int(stat["same_exif_count"]),
                int(stat["derivative_count"]),
                int(stat["collision_count"]),
                None,
                "{}",
                0.70,
                json_dumps(reason),
            ),
        )
        _insert_candidate(
            conn,
            scan_root_id,
            f"fpb:{folder_a}:{folder_b}",
            "folder_pair_burst",
            stat["sample_rows"],
            reason,
            0.70,
            "review_folder_pair",
        )
        count += 1
    return count
