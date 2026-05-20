from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ATTENTION_PATTERNS, EXISTENCE_MISSING, EXISTENCE_NOT_SEEN, EXISTENCE_SEEN, MEDIA_EXTENSIONS
from .schemas import utc_now_iso
from .utils import ext_lower, json_dumps, safe_rel

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


@dataclass
class ScanResult:
    scan_run_id: int
    folder_count: int
    file_count: int
    error_count: int


def _detect_attention_flags(path_lower: str) -> list[str]:
    flags: list[str] = []
    for token, flag in ATTENTION_PATTERNS.items():
        if token in path_lower:
            flags.append(flag)
    return sorted(set(flags))


def _extract_exif(path: Path) -> tuple[str | None, float | None, float | None]:
    if Image is None:
        return None, None, None
    try:
        with Image.open(path) as img:
            exif = img.getexif()
        if not exif:
            return None, None, None
        dt = exif.get(36867) or exif.get(306)
        exif_dt = str(dt).replace(" ", "T").replace(":", "-", 2) if dt else None
        gps = exif.get(34853)
        if not gps:
            return exif_dt, None, None
        lat = _gps_to_float(gps.get(2), gps.get(1))
        lon = _gps_to_float(gps.get(4), gps.get(3))
        return exif_dt, lat, lon
    except Exception:
        return None, None, None


def _gps_to_float(values: Any, ref: str | None) -> float | None:
    if not values:
        return None
    try:
        d = float(values[0][0]) / float(values[0][1])
        m = float(values[1][0]) / float(values[1][1])
        s = float(values[2][0]) / float(values[2][1])
        v = d + (m / 60.0) + (s / 3600.0)
        if ref in {"S", "W"}:
            v *= -1
        return round(v, 6)
    except Exception:
        return None


def run_scan(conn: sqlite3.Connection, scan_root_id: int, source_root: Path) -> ScanResult:
    started_at = utc_now_iso()
    cur = conn.execute(
        "INSERT INTO scan_runs(scan_root_id, status, started_at, details_json) VALUES(?, 'running', ?, '{}')",
        (scan_root_id, started_at),
    )
    run_id = int(cur.lastrowid)
    conn.commit()

    folder_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "direct_file_count": 0,
            "direct_bytes": 0,
            "subtree_file_count": 0,
            "subtree_bytes": 0,
            "extensions": defaultdict(int),
            "flags": set(),
            "min_mtime_ns": None,
            "max_mtime_ns": None,
        }
    )
    file_count = 0
    error_count = 0
    visited_folders: set[str] = set()

    for root, dirnames, filenames in os.walk(source_root, topdown=True):
        root_path = Path(root)
        try:
            if root_path.is_symlink():
                dirnames[:] = []
                continue
        except OSError:
            dirnames[:] = []
            continue
        rel_folder = "." if root_path == source_root else safe_rel(root_path, source_root)
        visited_folders.add(rel_folder)
        lower = rel_folder.lower()
        flags = _detect_attention_flags(lower)
        folder_stats[rel_folder]["flags"].update(flags)

        filtered_dirs: list[str] = []
        for d in dirnames:
            p = root_path / d
            try:
                if p.is_symlink():
                    continue
                filtered_dirs.append(d)
            except OSError:
                _insert_scan_error(conn, run_id, str(p), "walk", "inaccessible_dir")
                error_count += 1
        dirnames[:] = filtered_dirs

        for name in filenames:
            file_path = root_path / name
            try:
                st = file_path.stat()
            except OSError as exc:
                _insert_scan_error(conn, run_id, str(file_path), "stat", str(exc))
                error_count += 1
                continue
            suffix = ext_lower(name)
            media_type = MEDIA_EXTENSIONS.get(suffix)
            if media_type is None:
                continue
            rel_file = safe_rel(file_path, source_root)
            exif_dt, lat, lon = _extract_exif(file_path)
            conn.execute(
                """
                INSERT INTO media_files(
                  scan_root_id,path,folder_path,name,stem,suffix,media_type,size_bytes,ctime_ns,mtime_ns,exif_datetime,gps_lat,gps_lon,existence_state,last_seen_scan_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(scan_root_id, path) DO UPDATE SET
                  folder_path=excluded.folder_path,
                  name=excluded.name,
                  stem=excluded.stem,
                  suffix=excluded.suffix,
                  media_type=excluded.media_type,
                  size_bytes=excluded.size_bytes,
                  ctime_ns=excluded.ctime_ns,
                  mtime_ns=excluded.mtime_ns,
                  exif_datetime=excluded.exif_datetime,
                  gps_lat=excluded.gps_lat,
                  gps_lon=excluded.gps_lon,
                  existence_state=excluded.existence_state,
                  last_seen_scan_id=excluded.last_seen_scan_id
                """,
                (
                    scan_root_id,
                    rel_file,
                    rel_folder,
                    name,
                    Path(name).stem,
                    suffix,
                    media_type,
                    int(st.st_size),
                    int(st.st_ctime_ns),
                    int(st.st_mtime_ns),
                    exif_dt,
                    lat,
                    lon,
                    EXISTENCE_SEEN,
                    run_id,
                ),
            )
            file_count += 1
            stats = folder_stats[rel_folder]
            stats["direct_file_count"] += 1
            stats["direct_bytes"] += int(st.st_size)
            stats["extensions"][suffix] += 1
            mm = int(st.st_mtime_ns)
            stats["min_mtime_ns"] = mm if stats["min_mtime_ns"] is None else min(stats["min_mtime_ns"], mm)
            stats["max_mtime_ns"] = mm if stats["max_mtime_ns"] is None else max(stats["max_mtime_ns"], mm)

    for folder in sorted(visited_folders, key=lambda p: (p.count(os.sep), p)):
        _upsert_folder_node(conn, scan_root_id, run_id, folder, folder_stats[folder])

    _rollup_subtree(conn, scan_root_id, run_id)
    _apply_missing_state_transitions(conn, scan_root_id, run_id)

    conn.execute(
        """
        UPDATE scan_runs SET status='completed', finished_at=?, folder_count=?, file_count=?, error_count=?, details_json=?
        WHERE id=?
        """,
        (utc_now_iso(), len(visited_folders), file_count, error_count, json_dumps({"source_root": str(source_root)}), run_id),
    )
    conn.commit()
    return ScanResult(run_id, len(visited_folders), file_count, error_count)


def _insert_scan_error(conn: sqlite3.Connection, run_id: int, path: str, phase: str, error: str) -> None:
    conn.execute(
        "INSERT INTO scan_errors(scan_run_id,path,phase,error,created_at) VALUES(?,?,?,?,?)",
        (run_id, path, phase, error, utc_now_iso()),
    )


def _upsert_folder_node(conn: sqlite3.Connection, scan_root_id: int, run_id: int, rel_folder: str, stats: dict[str, Any]) -> None:
    parent = None
    depth = 0
    if rel_folder != ".":
        parent = str(Path(rel_folder).parent).replace("\\", "/")
        if parent == ".":
            parent = "."
        depth = rel_folder.count("\\") + rel_folder.count("/")
    min_ns = stats["min_mtime_ns"]
    max_ns = stats["max_mtime_ns"]
    date_ranges = {"mtime_ns_min": min_ns, "mtime_ns_max": max_ns}
    conn.execute(
        """
        INSERT INTO folder_nodes(
          scan_root_id,path,parent_path,depth,direct_file_count,subtree_file_count,direct_bytes,subtree_bytes,
          extension_counts_json,date_ranges_json,attention_flags_json,last_seen_scan_id
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(scan_root_id,path) DO UPDATE SET
          parent_path=excluded.parent_path,
          depth=excluded.depth,
          direct_file_count=excluded.direct_file_count,
          direct_bytes=excluded.direct_bytes,
          extension_counts_json=excluded.extension_counts_json,
          date_ranges_json=excluded.date_ranges_json,
          attention_flags_json=excluded.attention_flags_json,
          subtree_file_count=excluded.subtree_file_count,
          subtree_bytes=excluded.subtree_bytes,
          last_seen_scan_id=excluded.last_seen_scan_id
        """,
        (
            scan_root_id,
            rel_folder,
            parent,
            depth,
            stats["direct_file_count"],
            stats["direct_file_count"],
            stats["direct_bytes"],
            stats["direct_bytes"],
            json_dumps(dict(stats["extensions"])),
            json_dumps(date_ranges),
            json_dumps(sorted(stats["flags"])),
            run_id,
        ),
    )


def _rollup_subtree(conn: sqlite3.Connection, scan_root_id: int, run_id: int) -> None:
    rows = conn.execute(
        "SELECT path,direct_file_count,direct_bytes FROM folder_nodes WHERE scan_root_id=? AND last_seen_scan_id=?",
        (scan_root_id, run_id),
    ).fetchall()
    subtree_files: dict[str, int] = defaultdict(int)
    subtree_bytes: dict[str, int] = defaultdict(int)
    for row in rows:
        path = row["path"]
        parts = Path(path).parts if path != "." else (".",)
        prefixes = ["."]
        cur = Path(".")
        for p in parts:
            if p == ".":
                continue
            cur = cur / p
            prefixes.append(str(cur).replace("\\", "/"))
        for pref in prefixes:
            subtree_files[pref] += int(row["direct_file_count"])
            subtree_bytes[pref] += int(row["direct_bytes"])
    for path, files in subtree_files.items():
        conn.execute(
            "UPDATE folder_nodes SET subtree_file_count=?, subtree_bytes=? WHERE scan_root_id=? AND path=?",
            (files, subtree_bytes[path], scan_root_id, path),
        )


def _apply_missing_state_transitions(conn: sqlite3.Connection, scan_root_id: int, run_id: int) -> None:
    conn.execute(
        """
        UPDATE media_files
        SET existence_state = CASE
            WHEN existence_state = ? THEN ?
            WHEN existence_state = ? THEN ?
            ELSE existence_state
          END
        WHERE scan_root_id = ? AND (last_seen_scan_id IS NULL OR last_seen_scan_id <> ?)
        """,
        (EXISTENCE_NOT_SEEN, EXISTENCE_MISSING, EXISTENCE_SEEN, EXISTENCE_NOT_SEEN, scan_root_id, run_id),
    )
