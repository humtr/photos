from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from .utils import ensure_parent_dir, file_sha256, json_dumps


def export_folder_packets(conn: sqlite3.Connection, scan_root_id: int, out_dir: Path, gps_mode: str = "summary") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    folder_rows = conn.execute(
        """
        SELECT path,subtree_file_count,subtree_bytes,attention_flags_json,date_ranges_json
        FROM folder_nodes WHERE scan_root_id=?
        """,
        (scan_root_id,),
    ).fetchall()
    place_map = {
        str(r["folder_path"]): str(r["dominant_place"])
        for r in conn.execute("SELECT folder_path,dominant_place FROM folder_places WHERE scan_root_id=?", (scan_root_id,)).fetchall()
    }
    dup_by_folder: dict[str, list[dict]] = defaultdict(list)
    dup_rows = conn.execute(
        "SELECT candidate_type,left_path,right_path,evidence_json FROM duplicate_candidates WHERE scan_root_id=?",
        (scan_root_id,),
    ).fetchall()
    for r in dup_rows:
        for side in ("left_path", "right_path"):
            folder = str(Path(str(r[side])).parent).replace("\\", "/")
            dup_by_folder[folder].append(
                {"type": str(r["candidate_type"]), "left_path": str(r["left_path"]), "right_path": str(r["right_path"]), "evidence": str(r["evidence_json"])}
            )
    packet_paths: list[Path] = []
    for row in folder_rows:
        folder_path = str(row["path"])
        samples = conn.execute(
            """
            SELECT path,name,size_bytes,mtime_ns,exif_datetime,gps_lat,gps_lon
            FROM media_files WHERE scan_root_id=? AND folder_path=? AND existence_state='seen'
            ORDER BY size_bytes DESC LIMIT 5
            """,
            (scan_root_id, folder_path),
        ).fetchall()
        packet = {
            "schema_version": 1,
            "review_type": "folder_semantic_review",
            "gps_mode": gps_mode,
            "folder_path": folder_path,
            "counts": {"subtree_file_count": int(row["subtree_file_count"]), "subtree_bytes": int(row["subtree_bytes"])},
            "date_ranges": json.loads(str(row["date_ranges_json"])),
            "attention_flags": json.loads(str(row["attention_flags_json"])),
            "dominant_place": place_map.get(folder_path),
            "duplicate_insights": dup_by_folder.get(folder_path, []),
            "sample_files": [
                {
                    "path": str(s["path"]),
                    "name": str(s["name"]),
                    "size_bytes": int(s["size_bytes"]),
                    "mtime_ns": int(s["mtime_ns"]),
                    "exif_datetime": s["exif_datetime"],
                    "gps_lat": s["gps_lat"],
                    "gps_lon": s["gps_lon"],
                }
                for s in samples
            ],
        }
        target = out_dir / f"{folder_path.replace('/', '__').replace('.', '_root_')}.json"
        ensure_parent_dir(target)
        target.write_text(json_dumps(packet), encoding="utf-8")
        packet_paths.append(target)
    index = {"schema_version": 1, "scan_root_id": scan_root_id, "packet_count": len(packet_paths), "packets": [str(p.name) for p in packet_paths]}
    index_path = out_dir / "index.json"
    index_path.write_text(json_dumps(index), encoding="utf-8")
    return {"packet_count": len(packet_paths), "index_path": str(index_path), "index_sha256": file_sha256(index_path)}
