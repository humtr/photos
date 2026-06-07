from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any, Iterable

from .database import utc_now
from .hashing import iter_duplicate_group_members, iter_duplicate_hash_groups

MAX_SCREENING_BUCKET_MEMBERS = 200
MAX_EVIDENCE_SIZE_VARIANTS = 200
MIN_PROBABLE_DUPLICATE_BYTES = 64 * 1024


def _json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def _normalized_name(value: Any) -> str:
    return str(value).lower()


def _insert_candidate(
    con: sqlite3.Connection,
    *,
    key: str,
    kind: str,
    members: Iterable[sqlite3.Row],
    member_count: int,
    evidence: dict[str, Any],
    confidence: float,
    recommended_action: str,
) -> int:
    if member_count < 2:
        return 0
    evidence_json = _json(evidence)
    cur = con.execute(
        """
        INSERT INTO duplicate_candidates(
            candidate_key, candidate_type, status, confidence,
            recommended_action, evidence_json, created_at
        )
        VALUES(?, ?, 'pending_review', ?, ?, ?, ?)
        ON CONFLICT(candidate_key) DO UPDATE SET
            candidate_type = excluded.candidate_type,
            status = 'pending_review',
            confidence = excluded.confidence,
            recommended_action = excluded.recommended_action,
            evidence_json = excluded.evidence_json,
            created_at = excluded.created_at
        """,
        (key, kind, confidence, recommended_action, evidence_json, utc_now()),
    )
    if cur.lastrowid:
        candidate_id = int(cur.lastrowid)
    else:
        row = con.execute(
            "SELECT id FROM duplicate_candidates WHERE candidate_key = ?", (key,)
        ).fetchone()
        candidate_id = int(row["id"])
    con.execute("DELETE FROM candidate_members WHERE candidate_id = ?", (candidate_id,))
    for index, row in enumerate(members):
        con.execute(
            """
            INSERT OR REPLACE INTO candidate_members(candidate_id, path, member_role, evidence_json)
            VALUES(?, ?, ?, ?)
            """,
            (
                candidate_id,
                row["path"],
                "primary" if index == 0 else "peer",
                evidence_json,
            ),
        )
    return 1


def refresh_duplicate_candidates(con: sqlite3.Connection) -> dict[str, Any]:
    """Materialize duplicate review candidates into the product tables.

    The output is intentionally a *screening* list. Only exact SHA-256 groups are
    deterministic duplicates; size/name buckets require human or later backend review.
    """

    con.execute("DELETE FROM candidate_members")
    con.execute("DELETE FROM duplicate_candidates")
    con.create_function("photos_normalized_name", 1, _normalized_name, deterministic=True)

    inserted_by_type: dict[str, int] = defaultdict(int)

    for group in iter_duplicate_hash_groups(con):
        sha = str(group["sha256"])
        member_count = int(group["member_count"])
        inserted = _insert_candidate(
            con,
            key=f"exact:{sha}",
            kind="exact_duplicate",
            members=iter_duplicate_group_members(con, sha),
            member_count=member_count,
            evidence={
                "sha256": sha,
                "member_count": member_count,
                "rule": "same_sha256",
                "destructive_action_allowed": False,
            },
            confidence=1.0,
            recommended_action="review_keep_one_or_more",
        )
        inserted_by_type["exact_duplicate"] += inserted

    size_buckets = con.execute(
        """
        SELECT suffix, size_bytes, COUNT(*) AS member_count,
               COUNT(NULLIF(sha256, '')) AS hashed_count,
               COUNT(DISTINCT NULLIF(sha256, '')) AS distinct_hash_count
        FROM media_files
        WHERE exists_on_disk = 1
        GROUP BY suffix, size_bytes
        HAVING COUNT(*) > 1
        ORDER BY suffix, size_bytes
        """
    )
    for bucket in size_buckets:
        size = int(bucket["size_bytes"])
        suffix = str(bucket["suffix"])
        member_count = int(bucket["member_count"])
        if (
            int(bucket["hashed_count"]) == member_count
            and int(bucket["distinct_hash_count"]) == 1
        ):
            # Exact duplicates are already represented above.
            continue
        if size < MIN_PROBABLE_DUPLICATE_BYTES or member_count > MAX_SCREENING_BUCKET_MEMBERS:
            kind = "noisy_size_bucket"
            confidence = 0.20
            recommended = "ignore_until_user_filters"
        else:
            kind = "probable_duplicate_size_bucket"
            confidence = 0.55
            recommended = "hash_or_visual_review"
        inserted = _insert_candidate(
            con,
            key=f"size:{suffix}:{size}",
            kind=kind,
            members=con.execute(
                """
                SELECT *
                FROM media_files
                WHERE exists_on_disk = 1
                  AND suffix = ?
                  AND size_bytes = ?
                ORDER BY path
                LIMIT ?
                """,
                (suffix, size, MAX_SCREENING_BUCKET_MEMBERS),
            ),
            member_count=member_count,
            evidence={
                "suffix": suffix,
                "size_bytes": size,
                "member_count": member_count,
                "rule": "same_suffix_and_size",
            },
            confidence=confidence,
            recommended_action=recommended,
        )
        inserted_by_type[kind] += inserted

    name_groups = con.execute(
        """
        SELECT photos_normalized_name(name) AS normalized_name, COUNT(*) AS member_count,
               COUNT(DISTINCT parent_key) AS folder_count,
               COUNT(DISTINCT size_bytes) AS size_variant_count
        FROM media_files
        WHERE exists_on_disk = 1
        GROUP BY photos_normalized_name(name)
        HAVING COUNT(*) > 1
        ORDER BY photos_normalized_name(name)
        """
    )
    for group in name_groups:
        folder_count = int(group["folder_count"])
        if folder_count < 2:
            continue
        name = str(group["normalized_name"])
        member_count = int(group["member_count"])
        size_variant_count = int(group["size_variant_count"])
        sizes = [
            int(row["size_bytes"])
            for row in con.execute(
                """
                SELECT DISTINCT size_bytes
                FROM media_files
                WHERE exists_on_disk = 1
                  AND photos_normalized_name(name) = ?
                ORDER BY size_bytes
                LIMIT ?
                """,
                (name, MAX_EVIDENCE_SIZE_VARIANTS),
            )
        ]
        kind = (
            "same_name_collision"
            if size_variant_count > 1
            else "renamed_or_copied_name_match"
        )
        inserted = _insert_candidate(
            con,
            key=f"name:{name}",
            kind=kind,
            members=con.execute(
                """
                SELECT *
                FROM media_files
                WHERE exists_on_disk = 1
                  AND photos_normalized_name(name) = ?
                ORDER BY path
                LIMIT ?
                """,
                (name, MAX_SCREENING_BUCKET_MEMBERS),
            ),
            member_count=member_count,
            evidence={
                "name": name,
                "member_count": member_count,
                "folder_count": folder_count,
                "size_variant_count": size_variant_count,
                "size_variants": sizes,
                "size_variants_truncated": size_variant_count > len(sizes),
                "rule": "same_filename_across_folders",
            },
            confidence=0.70 if len(sizes) == 1 else 0.40,
            recommended_action="review_keep_separate_when_sizes_differ",
        )
        inserted_by_type[kind] += inserted

    con.commit()
    total = sum(inserted_by_type.values())
    return {"candidate_count": total, "by_type": dict(sorted(inserted_by_type.items()))}


def list_duplicate_candidates(
    con: sqlite3.Connection,
    *,
    candidate_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    filters = ["1 = 1"]
    params: list[Any] = []
    if candidate_type:
        filters.append("candidate_type = ?")
        params.append(candidate_type)
    where = " AND ".join(filters)
    total = int(
        con.execute(
            f"SELECT COUNT(*) AS count FROM duplicate_candidates WHERE {where}", params
        ).fetchone()["count"]
    )
    candidates = []
    for row in con.execute(
        f"""
        SELECT * FROM duplicate_candidates
        WHERE {where}
        ORDER BY confidence DESC, candidate_type, candidate_key
        LIMIT ? OFFSET ?
        """,
        [*params, max(1, min(1000, int(limit))), max(0, int(offset))],
    ):
        members = con.execute(
            """
            SELECT candidate_members.path, candidate_members.member_role,
                   media_files.size_bytes, media_files.media_type, media_files.sha256
            FROM candidate_members
            LEFT JOIN media_files ON media_files.path = candidate_members.path
            WHERE candidate_members.candidate_id = ?
            ORDER BY candidate_members.member_role DESC, candidate_members.path
            """,
            (row["id"],),
        ).fetchall()
        candidates.append(
            {
                "id": row["id"],
                "candidate_key": row["candidate_key"],
                "candidate_type": row["candidate_type"],
                "status": row["status"],
                "confidence": row["confidence"],
                "recommended_action": row["recommended_action"],
                "evidence": json.loads(row["evidence_json"] or "{}"),
                "members": [dict(member) for member in members],
            }
        )
    return {"total": total, "rows": candidates}
