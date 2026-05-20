from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .schemas import Message, utc_now_iso
from .utils import file_sha256, is_within, json_dumps

ALLOWED_PROPOSALS = {
    "folder_merge",
    "folder_split",
    "folder_rename",
    "date_override",
    "metadata_override",
    "duplicate_resolution",
}


def import_review(conn: sqlite3.Connection, scan_root_id: int, input_path: Path, source_root: Path) -> dict:
    paths = [input_path]
    if input_path.is_dir():
        paths = sorted([p for p in input_path.rglob("*.json") if p.is_file()])
    imported = 0
    rejected = 0
    errors: list[Message] = []
    for p in paths:
        ok, msg = _import_one(conn, scan_root_id, p, source_root)
        if ok:
            imported += 1
        else:
            rejected += 1
            errors.append(msg)
    conn.commit()
    return {"imported": imported, "rejected": rejected, "errors": [e.to_json() for e in errors]}


def _import_one(conn: sqlite3.Connection, scan_root_id: int, path: Path, source_root: Path) -> tuple[bool, Message]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, Message("invalid_json", f"invalid json: {exc}", phase="parse", path=str(path), recoverable=True)
    if int(raw.get("schema_version", 0)) != 1:
        return False, Message("unsupported_schema", "schema_version must be 1", phase="validate", path=str(path), recoverable=False)
    if "review_type" not in raw or "items" not in raw or not isinstance(raw["items"], list):
        return False, Message("invalid_schema", "missing review_type/items", phase="validate", path=str(path), recoverable=False)
    review_type = str(raw["review_type"])
    sha = file_sha256(path)
    cur = conn.execute(
        """
        INSERT INTO llm_reviews(review_type,path,status,imported_at,summary_json)
        VALUES(?,?,?,?,?)
        """,
        (
            review_type,
            str(path),
            "imported",
            utc_now_iso(),
            json_dumps({"scan_root_id": scan_root_id, "source_sha256": sha}),
        ),
    )
    review_id = int(cur.lastrowid)
    for item in raw["items"]:
        maybe_error = _validate_item(item, source_root)
        if maybe_error:
            return False, maybe_error
        conn.execute(
            """
            INSERT INTO llm_review_items(
              review_id,target_type,target_path,proposal_type,confidence,proposal_json,status
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                review_id,
                str(item["target_type"]),
                str(item["target_path"]),
                str(item["proposal_type"]),
                float(item["confidence"]),
                json_dumps(
                    {
                        "proposal": item["proposal"],
                        "evidence": item["evidence"],
                        "requires_user_approval": bool(item.get("requires_user_approval", True)),
                    }
                ),
                "pending_approval",
            ),
        )
    return True, Message("ok", "imported")


def _validate_item(item: dict, source_root: Path) -> Message | None:
    required = ["target_type", "target_path", "proposal_type", "confidence", "proposal", "evidence"]
    for r in required:
        if r not in item:
            return Message("invalid_item", f"missing {r}", phase="validate", recoverable=False)
    proposal_type = str(item["proposal_type"])
    if proposal_type not in ALLOWED_PROPOSALS:
        return Message("unknown_proposal_type", f"unknown proposal_type: {proposal_type}", phase="validate", recoverable=False)
    target_path = Path(str(item["target_path"]))
    if target_path.is_absolute():
        if not is_within(target_path, source_root):
            return Message("path_outside_root", "target_path outside scan root", phase="validate", path=str(target_path), recoverable=False)
    return None
