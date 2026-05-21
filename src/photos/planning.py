from __future__ import annotations

from pathlib import Path

from .store import Store
from .utils import json_dumps, normalize_case_path, parse_folder_date


def _dest_for_media(source_root: Path, archive_root: Path, media_path: Path, canonical_date: str | None = None) -> Path:
    rel = media_path.relative_to(source_root)
    if canonical_date:
        parts = list(rel.parts)
        for idx, part in enumerate(parts[:-1]):
            if parse_folder_date(part):
                parts[idx] = canonical_date
                return archive_root.joinpath(*parts)
        return archive_root / canonical_date / rel.name
    return archive_root / rel


def _approved_metadata_overrides(store: Store) -> dict[str, str]:
    rows = store.conn.execute(
        """
        SELECT target_path, proposed_value
        FROM metadata_edit_suggestions
        WHERE target_type='media_file' AND status='approved'
        ORDER BY id
        """
    ).fetchall()
    return {str(row["target_path"]): str(row["proposed_value"]) for row in rows}


def build_plan(store: Store, scan_root_id: int, strategy: str = "hybrid") -> int:
    root = store.get_scan_root(scan_root_id)
    source_root = Path(root["source_root"])
    archive_root = Path(root["archive_root"])
    media_rows = store.list_media(scan_root_id)
    metadata_overrides = _approved_metadata_overrides(store)

    seen_dest_ci: dict[str, int] = {}
    action_rows: list[tuple] = []
    move_count = 0
    hold_count = 0

    for row in media_rows:
        src = Path(row["path"])
        if normalize_case_path(str(src)).startswith(normalize_case_path(str(archive_root))):
            action_rows.append(
                (
                    str(src),
                    str(src),
                    "keep",
                    int(row["size_bytes"]),
                    int(row["mtime_ns"]),
                    "pending",
                    json_dumps({"reason": "already_in_archive_root"}),
                )
            )
            continue

        try:
            metadata_override = metadata_overrides.get(str(src))
            dst = _dest_for_media(source_root, archive_root, src, metadata_override)
        except ValueError:
            action_rows.append(
                (
                    str(src),
                    str(src),
                    "hold",
                    int(row["size_bytes"]),
                    int(row["mtime_ns"]),
                    "pending",
                    json_dumps({"reason": "outside_source_root"}),
                )
            )
            hold_count += 1
            continue

        ci = normalize_case_path(str(dst))
        action_type = "move"
        if ci in seen_dest_ci:
            action_type = "rename_move"
            suffix = seen_dest_ci[ci] + 1
            seen_dest_ci[ci] = suffix
            dst = dst.with_name(f"{dst.stem}__dup{suffix}{dst.suffix}")
        else:
            seen_dest_ci[ci] = 1

        action_rows.append(
            (
                str(src),
                str(dst),
                action_type,
                int(row["size_bytes"]),
                int(row["mtime_ns"]),
                "pending",
                json_dumps(
                    {"reason": "metadata_override", "canonical_date": metadata_override}
                    if metadata_override
                    else {"reason": "planned"}
                ),
            )
        )
        move_count += 1

    plan_id = store.create_plan(
        scan_root_id,
        strategy,
        str(archive_root),
        {"move_count": move_count, "hold_count": hold_count, "total_actions": len(action_rows)},
    )
    store.insert_plan_actions(plan_id, [(plan_id, *x) for x in action_rows])
    return plan_id
