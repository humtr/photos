import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
VENDOR_DIR = APP_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    from PIL import ExifTags, Image
except Exception as exc:  # pragma: no cover - shown in GUI at runtime
    Image = None
    ExifTags = None
    PIL_IMPORT_ERROR = exc
else:
    PIL_IMPORT_ERROR = None


PHOTO_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
    ".heic",
    ".heif",
    ".raw",
    ".cr2",
    ".nef",
    ".arw",
    ".dng",
}
HASH_CHUNK_SIZE = 1024 * 1024
MAX_SCAN_PREVIEW_ROWS = 1000
MAX_PLAN_PREVIEW_ROWS = 5000
MAX_FOLDER_ROWS = 10000
REVIEW_DIR_NAME = "_review"
DATE_PATTERNS = (
    re.compile(r"(?P<year>20\d{2}|19\d{2})[-_. ]?(?P<month>0[1-9]|1[0-2])[-_. ]?(?P<day>0[1-9]|[12]\d|3[01])"),
    re.compile(r"(?P<year>20\d{2}|19\d{2})[-_. ]?(?P<month>[1-9])[-_. ]?(?P<day>[1-9]|[12]\d|3[01])"),
)
EXIF_DATE_TAGS = ("DateTimeOriginal", "DateTimeDigitized", "DateTime")


@dataclass(frozen=True)
class PhotoRecord:
    path: str
    size: int
    created_at: float
    modified_at: float
    best_date: datetime
    date_source: str
    place: str
    sha256: str = ""
    phash: str = ""


@dataclass(frozen=True)
class PhotoCluster:
    kind: str
    score: str
    files: tuple[PhotoRecord, ...]


@dataclass(frozen=True)
class OrganizeAction:
    source: str
    destination: str
    reason: str


@dataclass
class FolderRecord:
    path: str
    parent: str
    depth: int
    subfolders: int = 0
    direct_files: int = 0
    direct_photos: int = 0
    total_files: int = 0
    total_photos: int = 0
    total_bytes: int = 0
    photo_bytes: int = 0
    extension_summary: str = ""
    role: str = ""
    include: bool = True
    review_status: str = ""


@dataclass(frozen=True)
class DateAuditRecord:
    path: str
    filename_date: str
    folder_date: str
    filesystem_date: str
    metadata_date: str
    status: str


def format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


def safe_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]+', "_", value.strip())
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .") or "Unknown"


def folder_role(path: str) -> str:
    lowered = path.lower()
    name = Path(path).name.lower()
    if name in {"$recycle.bin", "system volume information", "onedrivetemp"}:
        return "제외 후보"
    if ".thumbnails" in lowered or "\\.tmp" in lowered:
        return "제외 후보"
    if "google photos" in lowered or "samsung gallery" in lowered or "onedrive" in lowered:
        return "클라우드/동기화"
    if "backup" in lowered or "백업" in lowered:
        return "백업"
    if "fuji" in lowered or "x-t4" in lowered or "a6000" in lowered:
        return "카메라"
    if "dcim" in lowered or "camera" in lowered or "카메라" in lowered:
        return "카메라/폰"
    return ""


def is_excluded_folder(path: str) -> bool:
    return folder_role(path) == "제외 후보"


def default_include_for_path(path: str) -> bool:
    lowered = path.lower()
    role = folder_role(path)
    if role == "제외 후보":
        return False
    if role == "클라우드/동기화":
        return False
    if any(token in lowered for token in ("\\hyejin", "\\!이안", "\\휴대폰 백업", "\\돌사진 원본", "\\잔pc 바탕화면")):
        return True
    if any(token in lowered for token in ("fuji", "\\dcim", "\\camera")):
        return True
    return True


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        while chunk := file.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def hamming_distance(left: str, right: str) -> int:
    if not left or not right or len(left) != len(right):
        return 999
    return sum(a != b for a, b in zip(left, right))


class BKTree:
    def __init__(self):
        self.root = None

    def add(self, value: str, index: int) -> None:
        node = [value, [index], {}]
        if self.root is None:
            self.root = node
            return

        current = self.root
        while True:
            distance = hamming_distance(value, current[0])
            if distance == 0:
                current[1].append(index)
                return
            child = current[2].get(distance)
            if child is None:
                current[2][distance] = node
                return
            current = child

    def search(self, value: str, threshold: int) -> list[int]:
        if self.root is None:
            return []
        matches = []
        stack = [self.root]
        while stack:
            current = stack.pop()
            distance = hamming_distance(value, current[0])
            if distance <= threshold:
                matches.extend(current[1])
            lower = distance - threshold
            upper = distance + threshold
            for child_distance, child in current[2].items():
                if lower <= child_distance <= upper:
                    stack.append(child)
        return matches


def image_phash(path: str) -> str:
    if Image is None:
        return ""
    try:
        with Image.open(path) as image:
            image = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
            pixels = list(image.getdata())
    except Exception:
        return ""

    bits = []
    for y in range(8):
        row = pixels[y * 9 : (y + 1) * 9]
        for x in range(8):
            bits.append("1" if row[x] > row[x + 1] else "0")
    return "".join(bits)


def read_exif(image_path: str) -> dict[str, object]:
    if Image is None or ExifTags is None:
        return {}
    try:
        with Image.open(image_path) as image:
            raw = image.getexif()
            if not raw:
                return {}
            return {ExifTags.TAGS.get(tag, str(tag)): value for tag, value in raw.items()}
    except Exception:
        return {}


def parse_exif_date(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            pass
    return None


def parse_filename_date(path: str) -> datetime | None:
    name = Path(path).stem
    for pattern in DATE_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        try:
            return datetime(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            continue
    return None


def parse_folder_date(path: str) -> datetime | None:
    for part in reversed(Path(path).parts):
        parsed = parse_filename_date(part)
        if parsed:
            return parsed
    return None


def best_photo_date(path: str, stat: os.stat_result, exif: dict[str, object]) -> tuple[datetime, str]:
    for tag in EXIF_DATE_TAGS:
        parsed = parse_exif_date(exif.get(tag))
        if parsed:
            return parsed, f"EXIF {tag}"

    filename_date = parse_filename_date(path)
    if filename_date:
        return filename_date, "파일명"

    created = datetime.fromtimestamp(stat.st_ctime)
    modified = datetime.fromtimestamp(stat.st_mtime)
    if created <= modified:
        return created, "작성일"
    return modified, "수정일"


def fast_photo_date(path: str, stat: os.stat_result) -> tuple[datetime, str]:
    filename_date = parse_filename_date(path)
    if filename_date:
        return filename_date, "파일명"

    created = datetime.fromtimestamp(stat.st_ctime)
    modified = datetime.fromtimestamp(stat.st_mtime)
    if created <= modified:
        return created, "작성일"
    return modified, "수정일"


def exif_place(exif: dict[str, object]) -> str:
    gps = exif.get("GPSInfo")
    if not gps:
        return "NoLocation"
    return "GPS"


def iter_photo_paths(root: str, stop_event: threading.Event):
    for current_root, dir_names, file_names in os.walk(root):
        if stop_event.is_set():
            return
        dir_names[:] = [
            name
            for name in dir_names
            if not name.startswith(".") and not is_excluded_folder(str(Path(current_root, name)))
        ]
        for file_name in file_names:
            if stop_event.is_set():
                return
            path = Path(current_root, file_name)
            if path.suffix.lower() in PHOTO_EXTENSIONS:
                yield str(path)


class PhotoLibraryEngine:
    def __init__(self, on_progress, stop_event: threading.Event, cache_dir: str | None = None):
        self.on_progress = on_progress
        self.stop_event = stop_event
        self.cache_dir = cache_dir

    def scan_folder_structure(self, root: str) -> list[FolderRecord]:
        folders: list[FolderRecord] = []
        root_path = Path(root)
        for index, (current_root, dir_names, _file_names) in enumerate(os.walk(root), start=1):
            if self.stop_event.is_set():
                return folders
            path = Path(current_root)
            try:
                depth = len(path.relative_to(root_path).parts)
            except ValueError:
                depth = 0
            folders.append(
                FolderRecord(
                    path=str(path),
                    parent=str(path.parent) if path != root_path else "",
                    depth=depth,
                    subfolders=len(dir_names),
                    role=folder_role(str(path)),
                    include=default_include_for_path(str(path)),
                )
            )
            if index % 250 == 0:
                self.on_progress(f"폴더 구조 파악: {index:,}개 폴더 확인 중: {path}")
        return folders

    def analyze_folder_contents(self, folders: list[FolderRecord]) -> list[FolderRecord]:
        folder_map = {record.path: record for record in folders}
        extension_counts: dict[str, dict[str, int]] = {record.path: {} for record in folders}

        for index, record in enumerate(folders, start=1):
            if self.stop_event.is_set():
                return folders
            try:
                entries = list(os.scandir(record.path))
            except OSError:
                continue

            for entry in entries:
                if not entry.is_file(follow_symlinks=False):
                    continue
                try:
                    stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                extension = Path(entry.name).suffix.lower() or "[none]"
                record.direct_files += 1
                record.total_files += 1
                record.total_bytes += stat.st_size
                extension_counts[record.path][extension] = extension_counts[record.path].get(extension, 0) + 1
                if extension in PHOTO_EXTENSIONS:
                    record.direct_photos += 1
                    record.total_photos += 1
                    record.photo_bytes += stat.st_size

            if index % 250 == 0:
                self.on_progress(f"용량/개수/종류 파악: {index:,}/{len(folders):,}개 폴더 확인 중")

        for record in sorted(folders, key=lambda item: item.depth, reverse=True):
            parent = folder_map.get(record.parent)
            if not parent:
                continue
            parent.total_files += record.total_files
            parent.total_photos += record.total_photos
            parent.total_bytes += record.total_bytes
            parent.photo_bytes += record.photo_bytes

        for record in folders:
            counts = extension_counts.get(record.path, {})
            top = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:4]
            record.extension_summary = ", ".join(f"{ext}:{count}" for ext, count in top)
        return folders

    def audit_dates(self, root: str, include_metadata: bool = False, limit: int | None = None) -> list[DateAuditRecord]:
        results: list[DateAuditRecord] = []
        for index, path in enumerate(iter_photo_paths(root, self.stop_event), start=1):
            if self.stop_event.is_set():
                return results
            try:
                stat = os.stat(path)
            except OSError:
                continue

            filename_date = parse_filename_date(path)
            folder_date = parse_folder_date(str(Path(path).parent))
            filesystem_date = datetime.fromtimestamp(stat.st_mtime)
            metadata_date = None
            if include_metadata:
                exif = read_exif(path)
                for tag in EXIF_DATE_TAGS:
                    metadata_date = parse_exif_date(exif.get(tag))
                    if metadata_date:
                        break

            year_values = {
                "파일명": filename_date.year if filename_date else None,
                "상위폴더": folder_date.year if folder_date else None,
                "수정일": filesystem_date.year,
                "메타": metadata_date.year if metadata_date else None,
            }
            known_years = {value for value in year_values.values() if value}
            status = "일치" if len(known_years) <= 1 else "불일치"
            results.append(
                DateAuditRecord(
                    path=path,
                    filename_date=filename_date.strftime("%Y-%m-%d") if filename_date else "",
                    folder_date=folder_date.strftime("%Y-%m-%d") if folder_date else "",
                    filesystem_date=filesystem_date.strftime("%Y-%m-%d"),
                    metadata_date=metadata_date.strftime("%Y-%m-%d") if metadata_date else ("미확인" if not include_metadata else ""),
                    status=status,
                )
            )
            if index % 250 == 0:
                self.on_progress(f"날짜 근거 파악: 사진 {index:,}개 확인 중")
            if limit and len(results) >= limit:
                return results
        return results

    def scan(
        self,
        root: str,
        include_exif: bool = False,
        include_fingerprints: bool = False,
        on_record=None,
    ) -> list[PhotoRecord]:
        records: list[PhotoRecord] = []
        for index, path in enumerate(iter_photo_paths(root, self.stop_event), start=1):
            try:
                stat = os.stat(path)
                exif = read_exif(path) if include_exif or include_fingerprints else {}
                if include_exif or include_fingerprints:
                    best_date, source = best_photo_date(path, stat, exif)
                    place = exif_place(exif)
                else:
                    best_date, source = fast_photo_date(path, stat)
                    place = "Unscanned"
                sha256 = sha256_file(path) if include_fingerprints else ""
                phash = image_phash(path) if include_fingerprints else ""
                records.append(
                    PhotoRecord(
                        path=path,
                        size=stat.st_size,
                        created_at=stat.st_ctime,
                        modified_at=stat.st_mtime,
                        best_date=best_date,
                        date_source=source,
                        place=place,
                        sha256=sha256,
                        phash=phash,
                    )
                )
            except OSError:
                continue

            interval = 10 if include_fingerprints else 250
            label = "중복/유사 분석" if include_fingerprints else ("정밀 날짜 보강" if include_exif else "빠른 구조 스캔")
            if index % interval == 0:
                self.on_progress(f"{label}: 사진 {index:,}개 확인 중: {path}")
                if on_record:
                    on_record(records[-interval:])
        return records

    def enrich_exif(self, records: list[PhotoRecord]) -> list[PhotoRecord]:
        enriched = []
        for index, record in enumerate(records, start=1):
            if self.stop_event.is_set():
                return enriched
            try:
                stat = os.stat(record.path)
                exif = read_exif(record.path)
                best_date, source = best_photo_date(record.path, stat, exif)
                place = exif_place(exif)
            except OSError:
                continue
            enriched.append(
                PhotoRecord(
                    path=record.path,
                    size=record.size,
                    created_at=record.created_at,
                    modified_at=record.modified_at,
                    best_date=best_date,
                    date_source=source,
                    place=place,
                    sha256=record.sha256,
                    phash=record.phash,
                )
            )
            if index % 25 == 0:
                self.on_progress(f"정밀 날짜 보강: EXIF {index:,}/{len(records):,}개 확인 중")
        return enriched

    def add_fingerprints(self, records: list[PhotoRecord]) -> list[PhotoRecord]:
        from collections import defaultdict
        import sqlite3

        # Group records by (suffix, size) and name.lower()
        size_suffix_groups = defaultdict(list)
        name_groups = defaultdict(list)

        for record in records:
            name = os.path.basename(record.path).lower()
            suffix = os.path.splitext(record.path)[1].lower()
            size_suffix_groups[(suffix, record.size)].append(record)
            name_groups[name].append(record)

        candidate_paths = set()
        for group in size_suffix_groups.values():
            if len(group) > 1:
                for r in group:
                    candidate_paths.add(r.path)
        for group in name_groups.values():
            if len(group) > 1:
                for r in group:
                    candidate_paths.add(r.path)

        db_conn = None
        if self.cache_dir:
            try:
                db_dir = Path(self.cache_dir) / ".photos-data"
                db_dir.mkdir(parents=True, exist_ok=True)
                db_path = db_dir / "photos_gui_cache.db"
                db_conn = sqlite3.connect(str(db_path))
                cursor = db_conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS media_fingerprints (
                        path TEXT PRIMARY KEY,
                        size INTEGER,
                        mtime REAL,
                        sha256 TEXT,
                        phash TEXT,
                        cached_at TEXT
                    )
                """)
                db_conn.commit()
            except Exception:
                db_conn = None

        fingerprinted = []
        skipped_count = 0
        hashed_count = 0
        hashed_bytes = 0
        total_candidates = sum(1 for r in records if r.path in candidate_paths)
        processed_candidates = 0
        start_time = time.time()

        try:
            for index, record in enumerate(records, start=1):
                if self.stop_event.is_set():
                    return fingerprinted

                if record.path not in candidate_paths:
                    # Unique record, skip computing hashes
                    fingerprinted.append(record)
                else:
                    processed_candidates += 1
                    sha256 = None
                    phash = None

                    # 1. Query DB cache first
                    if db_conn:
                        try:
                            cursor = db_conn.cursor()
                            cursor.execute(
                                "SELECT sha256, phash FROM media_fingerprints WHERE path = ? AND size = ? AND mtime = ?",
                                (record.path, record.size, record.modified_at)
                            )
                            row = cursor.fetchone()
                            if row:
                                sha256, phash = row
                                if sha256 and phash:
                                    skipped_count += 1
                        except sqlite3.Error:
                            pass

                    # 2. Cache Miss or no cache
                    if sha256 is None or phash is None:
                        try:
                            sha256 = record.sha256 or sha256_file(record.path)
                            phash = record.phash or image_phash(record.path)
                            hashed_count += 1
                            hashed_bytes += record.size

                            if db_conn:
                                try:
                                    cursor = db_conn.cursor()
                                    cached_at = datetime.now().isoformat()
                                    cursor.execute(
                                        """
                                        INSERT OR REPLACE INTO media_fingerprints (path, size, mtime, sha256, phash, cached_at)
                                        VALUES (?, ?, ?, ?, ?, ?)
                                        """,
                                        (record.path, record.size, record.modified_at, sha256, phash, cached_at)
                                    )
                                    db_conn.commit()
                                except sqlite3.Error:
                                    pass
                        except OSError:
                            continue

                    fingerprinted.append(
                        PhotoRecord(
                            path=record.path,
                            size=record.size,
                            created_at=record.created_at,
                            modified_at=record.modified_at,
                            best_date=record.best_date,
                            date_source=record.date_source,
                            place=record.place,
                            sha256=sha256,
                            phash=phash,
                        )
                    )

                if index % 10 == 0 or index == len(records):
                    # Compute telemetry
                    telemetry_dict = {
                        "speed": "0.0 files/s (0.0 MB/s)",
                        "eta": "대기 중",
                        "extrap_500k": "대기 중"
                    }
                    if processed_candidates > 0:
                        elapsed = time.time() - start_time
                        if hashed_count > 0 and elapsed > 0.1:
                            files_per_sec = hashed_count / elapsed
                            mb_per_sec = (hashed_bytes / (1024 * 1024)) / elapsed
                            remaining = total_candidates - processed_candidates
                            eta_secs = remaining / files_per_sec
                            extrap_secs = 500000 / files_per_sec

                            speed_text = f"{files_per_sec:.1f} files/s ({mb_per_sec:.1f} MB/s)"

                            if eta_secs < 60:
                                eta_text = f"{int(eta_secs)}초"
                            else:
                                eta_text = f"{int(eta_secs // 60)}분 {int(eta_secs % 60)}초"

                            extrap_hours = extrap_secs / 3600
                            if extrap_hours < 1.0:
                                extrap_text = f"{int(extrap_hours * 60)}분"
                            else:
                                extrap_text = f"{extrap_hours:.1f}시간"
                        elif skipped_count > 0:
                            speed_text = "Instant (Cache Hit)"
                            eta_text = "0s (Cached)"
                            extrap_text = "Instant (Cached)"
                        else:
                            speed_text = "0.0 files/s (0.0 MB/s)"
                            eta_text = "계산 중..."
                            extrap_text = "계산 중..."

                        telemetry_dict = {
                            "speed": speed_text,
                            "eta": eta_text,
                            "extrap_500k": extrap_text
                        }

                    progress_text = f"중복/유사 분석: 이미지 지문 {index:,}/{len(records):,}개 계산 중"
                    try:
                        self.on_progress(progress_text, telemetry=telemetry_dict)
                    except TypeError:
                        self.on_progress(progress_text)
        finally:
            if db_conn:
                try:
                    db_conn.close()
                except sqlite3.Error:
                    pass

        return fingerprinted


    def duplicate_clusters(self, records: list[PhotoRecord], similar_threshold: int) -> list[PhotoCluster]:
        clusters: list[PhotoCluster] = []
        exact: dict[str, list[PhotoRecord]] = {}
        for record in records:
            if record.sha256:
                exact.setdefault(record.sha256, []).append(record)
        for files in exact.values():
            if len(files) > 1:
                clusters.append(PhotoCluster("동일", "SHA-256 일치", tuple(sorted(files, key=lambda item: item.path.lower()))))

        phash_records = [record for record in records if record.phash]
        parents = list(range(len(phash_records)))
        tree = BKTree()

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left: int, right: int) -> None:
            left_parent = find(left)
            right_parent = find(right)
            if left_parent != right_parent:
                parents[right_parent] = left_parent

        for index, record in enumerate(phash_records):
            for match_index in tree.search(record.phash, similar_threshold):
                match = phash_records[match_index]
                if record.sha256 != match.sha256:
                    union(index, match_index)
            tree.add(record.phash, index)

        similar_groups: dict[int, list[PhotoRecord]] = {}
        for index, record in enumerate(phash_records):
            root = find(index)
            similar_groups.setdefault(root, []).append(record)

        for files_list in similar_groups.values():
            hashes = {record.sha256 for record in files_list}
            if len(files_list) > 1 and len(hashes) > 1:
                files = tuple(sorted(files_list, key=lambda item: item.path.lower()))
                clusters.append(PhotoCluster("유사", f"dHash 거리 <= {similar_threshold}", files))

        clusters.sort(key=lambda cluster: (cluster.kind != "동일", -len(cluster.files), cluster.files[0].path.lower()))
        return clusters

    def build_organize_plan(self, records: list[PhotoRecord], destination_root: str, mode: str, scheme: str = "year_month_event") -> list[OrganizeAction]:
        actions: list[OrganizeAction] = []
        destination_root_path = Path(destination_root)
        for record in records:
            date = record.best_date
            if scheme == "year_source_month":
                source_name = "camera" if "camera" in record.path.lower() or "dcim" in record.path.lower() else ("cloud" if "onedrive" in record.path.lower() or "google" in record.path.lower() else "photo")
                folder = destination_root_path / f"{date:%Y}" / source_name / f"{date:%m}"
            elif scheme == "year_month_day":
                folder = destination_root_path / f"{date:%Y}" / f"{date:%m}" / f"{date:%d}"
            else:
                if mode == "date_place":
                    place_suffix = "" if record.place == "Unscanned" else f" {record.place}"
                    folder = destination_root_path / f"{date:%Y}" / f"{date:%m}" / safe_name(f"{date:%Y-%m-%d}{place_suffix}")
                else:
                    place_suffix = "" if record.place == "Unscanned" else f" {record.place}"
                    folder = destination_root_path / f"{date:%Y}" / safe_name(f"{date:%Y-%m}{place_suffix}")

            suffix = record.sha256[:8] if record.sha256 else hashlib.sha1(record.path.encode("utf-8")).hexdigest()[:8]
            target_name = self._unique_target_name(folder, Path(record.path).name, suffix)
            actions.append(OrganizeAction(record.path, str(folder / target_name), record.date_source))
        return actions

    def _unique_target_name(self, folder: Path, name: str, suffix: str) -> str:
        candidate = folder / name
        if not candidate.exists():
            return name
        stem = candidate.stem
        extension = candidate.suffix
        return f"{stem}_{suffix}{extension}"


class PhotoOrganizerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Photo Organizer")
        self.geometry("1180x760")
        self.minsize(980, 620)

        self.source_var = tk.StringVar(value="D:\\")
        self.destination_var = tk.StringVar(value="D:\\PICTURES")
        self.threshold_var = tk.IntVar(value=10)
        self.mode_var = tk.StringVar(value="year_month_place")
        self.plan_scheme_var = tk.StringVar(value="year_month_event")
        self.read_only_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="빠른 구조 스캔은 파일명과 파일 시스템 날짜만 사용합니다.")
        self.summary_var = tk.StringVar(value="사진 0개")
        self.telemetry_speed_var = tk.StringVar(value="0.0 files/s (0.0 MB/s)")
        self.telemetry_eta_var = tk.StringVar(value="대기 중")
        self.telemetry_500k_var = tk.StringVar(value="대기 중")
        self.scan_preview_count = 0

        self.folders: list[FolderRecord] = []
        self.folder_map: dict[str, FolderRecord] = {}
        self.folder_tree_children: dict[str, list[str]] = {}
        self.folder_state_marks: dict[str, str] = {}
        self.date_audit: list[DateAuditRecord] = []
        self.records: list[PhotoRecord] = []
        self.clusters: list[PhotoCluster] = []
        self.filename_duplicates: dict[str, list[str]] = {}
        self.plan: list[OrganizeAction] = []
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self._refresh_debounce_timer = None
        self._cluster_thread = None

        self._build_ui()
        self._build_state_icons()
        if PIL_IMPORT_ERROR:
            messagebox.showwarning("이미지 라이브러리 필요", f"Pillow 로드 실패: {PIL_IMPORT_ERROR}")

    def _build_state_icons(self) -> None:
        self.icon_checked = self._make_checkbox_icon("#1f8f3a", "checked")
        self.icon_partial = self._make_checkbox_icon("#d98a00", "partial")
        self.icon_unchecked = self._make_checkbox_icon("#8a8f98", "unchecked")

    def _make_checkbox_icon(self, color: str, state: str) -> tk.PhotoImage:
        size = 14
        image = tk.PhotoImage(width=size, height=size)
        for y in range(size):
            for x in range(size):
                image.put("#ffffff", (x, y))
        border = "#5a5f66"
        for i in range(size):
            image.put(border, (i, 0))
            image.put(border, (i, size - 1))
            image.put(border, (0, i))
            image.put(border, (size - 1, i))
        for y in range(2, size - 2):
            for x in range(2, size - 2):
                image.put(color if state != "unchecked" else "#f7f8fa", (x, y))
        if state == "checked":
            for x, y in ((3, 7), (4, 8), (5, 9), (6, 8), (7, 7), (8, 6), (9, 5), (10, 4)):
                image.put("#ffffff", (x, y))
        elif state == "partial":
            for y in (6, 7):
                for x in range(3, 11):
                    image.put("#ffffff", (x, y))
        return image

    def _lock_tree_header_drag(self, tree: ttk.Treeview) -> None:
        def block_drag(event):
            region = tree.identify_region(event.x, event.y)
            if region in {"separator", "heading"}:
                return "break"
            return None

        tree.bind("<ButtonPress-1>", block_drag, add="+")

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(14, 12, 14, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="원본").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(header, textvariable=self.source_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(header, text="폴더 선택", command=self._choose_source).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(header, text="1 구조 개요", command=self._start_structure_overview).grid(row=0, column=3, padx=(8, 0))
        ttk.Button(header, text="2 폴더 상세 구조", command=self._start_folder_detail).grid(row=0, column=4, padx=(8, 0))
        ttk.Button(header, text="3 날짜 근거", command=self._start_date_audit).grid(row=0, column=5, padx=(8, 0))
        ttk.Button(header, text="4 사진 메타데이터", command=self._start_photo_metadata).grid(row=0, column=6, padx=(8, 0))
        ttk.Button(header, text="5 파일명 중복검사", command=self._start_filename_duplicate_scan).grid(row=0, column=7, padx=(8, 0))
        ttk.Button(header, text="Review 저장", command=self._export_review_bundle).grid(row=0, column=8, padx=(8, 0))
        ttk.Button(header, text="Review 로드", command=self._load_codex_review).grid(row=0, column=9, padx=(8, 0))
        ttk.Button(header, text="Dry-run", command=self._run_dry_run).grid(row=0, column=10, padx=(8, 0))
        ttk.Button(header, text="중지", command=self._stop).grid(row=0, column=11, padx=(8, 0))

        tabs = ttk.Notebook(self)
        tabs.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 8))

        self.folder_tab = ttk.Frame(tabs)
        self.date_tab = ttk.Frame(tabs)
        self.scan_tab = ttk.Frame(tabs)
        self.duplicates_tab = ttk.Frame(tabs)
        self.organize_tab = ttk.Frame(tabs)
        self.notes_tab = ttk.Frame(tabs)
        tabs.add(self.folder_tab, text="폴더 구조")
        tabs.add(self.date_tab, text="날짜 근거")
        tabs.add(self.scan_tab, text="사진 목록")
        tabs.add(self.duplicates_tab, text="중복/유사 사진")
        tabs.add(self.organize_tab, text="정리 계획")
        tabs.add(self.notes_tab, text="정리 기준")

        self._build_folder_tab()
        self._build_date_tab()
        self._build_scan_tab()
        self._build_duplicates_tab()
        self._build_organize_tab()
        self._build_notes_tab()

        footer = ttk.Frame(self, padding=(14, 0, 14, 12))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.summary_var).grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.status_var).grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _build_folder_tab(self) -> None:
        self.folder_tab.columnconfigure(0, weight=1)
        self.folder_tab.rowconfigure(1, weight=1)

        bar = ttk.Frame(self.folder_tab, padding=(0, 8, 0, 8))
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            bar,
            text="1단계는 폴더명/깊이/하위폴더만 파악합니다. 2단계에서 파일 수, 사진 수, 용량, 확장자 구성을 채웁니다.",
        ).grid(row=0, column=0, sticky="w")

        split = ttk.PanedWindow(self.folder_tab, orient=tk.HORIZONTAL)
        split.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(split)
        mid = ttk.Frame(split)
        right = ttk.Frame(split)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        split.add(left, weight=3)
        split.add(mid, weight=2)
        split.add(right, weight=2)

        self.folder_tree = ttk.Treeview(
            left,
            columns=("role", "subfolders", "files", "photos", "bytes", "extensions", "review"),
            show="tree headings",
        )
        self.folder_tree.heading("#0", text="폴더")
        self.folder_tree.column("#0", width=430, anchor=tk.W)
        for column, label, width in (
            ("role", "분류", 110),
            ("subfolders", "하위", 60),
            ("files", "파일", 80),
            ("photos", "사진", 80),
            ("bytes", "용량", 100),
            ("extensions", "종류", 130),
            ("review", "검수", 80),
        ):
            self.folder_tree.heading(column, text=label)
            self.folder_tree.column(column, width=width, anchor=tk.W)
        self.folder_tree.grid(row=0, column=0, sticky="nsew")
        self.folder_tree.bind("<Button-1>", self._on_folder_tree_click)
        self.folder_tree.tag_configure("state_checked", background="#f3fbf5")
        self.folder_tree.tag_configure("state_partial", background="#fff8ec")
        self.folder_tree.tag_configure("state_unchecked", background="#f7f8fa")

        scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.folder_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.folder_tree.configure(yscrollcommand=scroll.set)
        self._lock_tree_header_drag(self.folder_tree)

        ttk.Label(
            mid,
            text="체크한 폴더 기준 정리 대상(요약)",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.selected_tree = ttk.Treeview(
            mid,
            columns=("files", "photos", "bytes"),
            show="tree headings",
        )
        self.selected_tree.heading("#0", text="선택 루트/폴더")
        self.selected_tree.column("#0", width=360, anchor=tk.W)
        for column, label, width in (("files", "파일", 70), ("photos", "사진", 70), ("bytes", "용량", 90)):
            self.selected_tree.heading(column, text=label)
            self.selected_tree.column(column, width=width, anchor=tk.W)
        self.selected_tree.grid(row=1, column=0, sticky="nsew")
        self.selected_tree.bind("<Button-1>", self._on_selected_tree_click)
        selected_scroll = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self.selected_tree.yview)
        selected_scroll.grid(row=1, column=1, sticky="ns")
        self.selected_tree.configure(yscrollcommand=selected_scroll.set)
        self._lock_tree_header_drag(self.selected_tree)

        ttk.Label(
            right,
            text="정리 제외 폴더(요약)",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.excluded_tree = ttk.Treeview(
            right,
            columns=("files", "photos", "bytes"),
            show="tree headings",
        )
        self.excluded_tree.heading("#0", text="제외 루트/폴더")
        self.excluded_tree.column("#0", width=360, anchor=tk.W)
        for column, label, width in (("files", "파일", 70), ("photos", "사진", 70), ("bytes", "용량", 90)):
            self.excluded_tree.heading(column, text=label)
            self.excluded_tree.column(column, width=width, anchor=tk.W)
        self.excluded_tree.grid(row=1, column=0, sticky="nsew")
        self.excluded_tree.bind("<Button-1>", self._on_excluded_tree_click)
        excluded_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.excluded_tree.yview)
        excluded_scroll.grid(row=1, column=1, sticky="ns")
        self.excluded_tree.configure(yscrollcommand=excluded_scroll.set)
        self._lock_tree_header_drag(self.excluded_tree)

        self.folder_tree.bind("<Button-3>", self._on_folder_tree_right_click)
        self.selected_tree.bind("<Button-3>", self._on_selected_tree_right_click)
        self.excluded_tree.bind("<Button-3>", self._on_excluded_tree_right_click)

        self.folder_menu = tk.Menu(self, tearoff=0)
        self.folder_menu.add_command(label="탐색기에서 열기", command=self._menu_open_in_explorer)
        self.folder_menu.add_command(label="왼쪽 패널로 포커스", command=self._menu_focus_left)
        self.folder_menu.add_separator()
        self.folder_menu.add_command(label="정리 대상 포함", command=self._menu_include_target)
        self.folder_menu.add_command(label="정리 대상 제외", command=self._menu_exclude_target)
        self.folder_menu.add_command(label="하위 전체 포함", command=self._menu_include_subtree)
        self.folder_menu.add_command(label="하위 전체 제외", command=self._menu_exclude_subtree)
        self.folder_menu.add_separator()
        self.folder_menu.add_command(label="경로 복사", command=self._menu_copy_path)
        self._menu_target_path: str | None = None

    def _build_date_tab(self) -> None:
        self.date_tab.columnconfigure(0, weight=1)
        self.date_tab.rowconfigure(1, weight=1)

        bar = ttk.Frame(self.date_tab, padding=(0, 8, 0, 8))
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            bar,
            text="파일명 날짜, 상위 폴더 날짜, 수정일, 메타데이터 날짜를 나란히 표시하고 연도가 다르면 불일치로 표시합니다.",
        ).grid(row=0, column=0, sticky="w")

        self.date_tree = ttk.Treeview(
            self.date_tab,
            columns=("status", "filename", "folder", "filesystem", "metadata", "path"),
            show="headings",
        )
        for column, label, width in (
            ("status", "상태", 70),
            ("filename", "파일명", 100),
            ("folder", "상위폴더", 100),
            ("filesystem", "수정일", 100),
            ("metadata", "메타", 100),
            ("path", "파일", 700),
        ):
            self.date_tree.heading(column, text=label)
            self.date_tree.column(column, width=width, anchor=tk.W)
        self.date_tree.grid(row=1, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(self.date_tab, orient=tk.VERTICAL, command=self.date_tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.date_tree.configure(yscrollcommand=scroll.set)
        self._lock_tree_header_drag(self.date_tree)

    def _build_scan_tab(self) -> None:
        self.scan_tab.columnconfigure(0, weight=1)
        self.scan_tab.rowconfigure(1, weight=1)

        bar = ttk.Frame(self.scan_tab, padding=(0, 8, 0, 8))
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            bar,
            text=f"최근 스캔 파일 최대 {MAX_SCAN_PREVIEW_ROWS:,}개만 표시합니다. 전체 목록은 메모리에 보관되고 정리 계획/CSV에 반영됩니다.",
        ).grid(row=0, column=0, sticky="w")

        self.scan_tree = ttk.Treeview(self.scan_tab, columns=("path", "date", "source", "size"), show="headings")
        for column, label, width in (
            ("path", "파일", 700),
            ("date", "기준 날짜", 150),
            ("source", "날짜 기준", 90),
            ("size", "크기", 100),
        ):
            self.scan_tree.heading(column, text=label)
            self.scan_tree.column(column, width=width, anchor=tk.W)
        self.scan_tree.grid(row=1, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(self.scan_tab, orient=tk.VERTICAL, command=self.scan_tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.scan_tree.configure(yscrollcommand=scroll.set)
        self._lock_tree_header_drag(self.scan_tree)

    def _build_duplicates_tab(self) -> None:
        self.duplicates_tab.columnconfigure(0, weight=1)
        self.duplicates_tab.columnconfigure(1, weight=2)
        self.duplicates_tab.rowconfigure(2, weight=1)

        controls = ttk.Frame(self.duplicates_tab, padding=(0, 8, 0, 8))
        controls.grid(row=0, column=0, columnspan=2, sticky="ew")
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="유사도 임계값").grid(row=0, column=0, sticky="w")
        ttk.Scale(
            controls,
            from_=2,
            to=20,
            variable=self.threshold_var,
            orient=tk.HORIZONTAL,
            command=lambda _: self._refresh_clusters(),
        ).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(controls, text="중복/유사 분석", command=self._start_duplicate_scan).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(controls, text="CSV 저장", command=self._export_clusters).grid(row=0, column=3)

        # Telemetry frame layout
        telemetry_frame = ttk.LabelFrame(self.duplicates_tab, text="실시간 분석 상태 및 캐시 제어", padding=(10, 6, 10, 6))
        telemetry_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        telemetry_frame.columnconfigure(8, weight=1)

        ttk.Label(telemetry_frame, text="분석 속도: ").grid(row=0, column=0, sticky="w")
        lbl_speed = tk.Label(
            telemetry_frame,
            textvariable=self.telemetry_speed_var,
            font=("Consolas", 10, "bold"),
            fg="#1a73e8"
        )
        lbl_speed.grid(row=0, column=1, sticky="w", padx=(0, 20))

        ttk.Label(telemetry_frame, text="남은 시간(ETA): ").grid(row=0, column=2, sticky="w")
        lbl_eta = tk.Label(
            telemetry_frame,
            textvariable=self.telemetry_eta_var,
            font=("Consolas", 10, "bold"),
            fg="#d93025"
        )
        lbl_eta.grid(row=0, column=3, sticky="w", padx=(0, 20))

        ttk.Label(telemetry_frame, text="50만 장 처리 예측: ").grid(row=0, column=4, sticky="w")
        lbl_500k = tk.Label(
            telemetry_frame,
            textvariable=self.telemetry_500k_var,
            font=("Consolas", 10, "bold"),
            fg="#188038"
        )
        lbl_500k.grid(row=0, column=5, sticky="w", padx=(0, 20))

        btn_delete_cache = ttk.Button(
            telemetry_frame,
            text="데이터베이스 캐시 삭제",
            command=self._delete_db_cache
        )
        btn_delete_cache.grid(row=0, column=9, sticky="e")

        self.cluster_tree = ttk.Treeview(self.duplicates_tab, columns=("kind", "count", "score"), show="headings")
        for column, label, width in (("kind", "유형", 90), ("count", "파일 수", 80), ("score", "판정", 160)):
            self.cluster_tree.heading(column, text=label)
            self.cluster_tree.column(column, width=width, anchor=tk.W)
        self.cluster_tree.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        self.cluster_tree.bind("<<TreeviewSelect>>", self._show_cluster_files)

        self.cluster_files = ttk.Treeview(self.duplicates_tab, columns=("path", "date", "size"), show="headings")
        for column, label, width in (("path", "파일", 620), ("date", "기준 날짜", 150), ("size", "크기", 100)):
            self.cluster_files.heading(column, text=label)
            self.cluster_files.column(column, width=width, anchor=tk.W)
        self.cluster_files.grid(row=2, column=1, sticky="nsew")
        self.cluster_files.bind("<Double-1>", self._open_selected_cluster_file)
        self._lock_tree_header_drag(self.cluster_tree)
        self._lock_tree_header_drag(self.cluster_files)

    def _build_organize_tab(self) -> None:
        self.organize_tab.columnconfigure(0, weight=1)
        self.organize_tab.rowconfigure(1, weight=1)

        controls = ttk.Frame(self.organize_tab, padding=(0, 8, 0, 8))
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="정리 대상 폴더").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(controls, textvariable=self.destination_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(controls, text="선택", command=self._choose_destination).grid(row=0, column=2, padx=(8, 0))
        ttk.Combobox(
            controls,
            textvariable=self.mode_var,
            values=("year_month_place", "date_place", "year_month"),
            state="readonly",
            width=14,
        ).grid(row=0, column=3, padx=(8, 0))
        ttk.Combobox(
            controls,
            textvariable=self.plan_scheme_var,
            values=("year_month_event", "year_source_month", "year_month_day"),
            state="readonly",
            width=16,
        ).grid(row=0, column=4, padx=(8, 0))
        ttk.Button(controls, text="계획 생성", command=self._build_plan).grid(row=0, column=5, padx=(8, 0))
        ttk.Checkbutton(controls, text="읽기 전용", variable=self.read_only_var).grid(row=0, column=6, padx=(8, 0))
        ttk.Button(controls, text="실행", command=self._execute_plan).grid(row=0, column=7, padx=(8, 0))
        ttk.Button(controls, text="계획 CSV", command=self._export_plan).grid(row=0, column=8, padx=(8, 0))

        split = ttk.PanedWindow(self.organize_tab, orient=tk.HORIZONTAL)
        split.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(split)
        right = ttk.Frame(split)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        split.add(left, weight=3)
        split.add(right, weight=2)

        self.plan_tree = ttk.Treeview(left, columns=("count", "bytes", "reason"), show="tree headings")
        self.plan_tree.heading("#0", text="정리 후 폴더/파일")
        self.plan_tree.column("#0", width=620, anchor=tk.W)
        for column, label, width in (("count", "건수", 80), ("bytes", "용량", 100), ("reason", "기준", 240)):
            self.plan_tree.heading(column, text=label)
            self.plan_tree.column(column, width=width, anchor=tk.W)
        self.plan_tree.grid(row=0, column=0, sticky="nsew")
        self._lock_tree_header_drag(self.plan_tree)

        plan_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.plan_tree.yview)
        plan_scroll.grid(row=0, column=1, sticky="ns")
        self.plan_tree.configure(yscrollcommand=plan_scroll.set)

        self.plan_review_tree = ttk.Treeview(right, columns=("value",), show="tree headings")
        self.plan_review_tree.heading("#0", text="계획 검토")
        self.plan_review_tree.column("#0", width=300, anchor=tk.W)
        self.plan_review_tree.heading("value", text="값")
        self.plan_review_tree.column("value", width=260, anchor=tk.W)
        self.plan_review_tree.grid(row=0, column=0, sticky="nsew")
        self._lock_tree_header_drag(self.plan_review_tree)
        review_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.plan_review_tree.yview)
        review_scroll.grid(row=0, column=1, sticky="ns")
        self.plan_review_tree.configure(yscrollcommand=review_scroll.set)

    def _build_notes_tab(self) -> None:
        self.notes_tab.columnconfigure(0, weight=1)
        self.notes_tab.rowconfigure(0, weight=1)
        text = tk.Text(self.notes_tab, wrap="word", padx=12, pady=12, height=12)
        text.grid(row=0, column=0, sticky="nsew")
        text.insert(
            "1.0",
            "권장 기준\n"
            "\n"
            "1. 원본 파일은 날짜 기반 폴더로 정리하는 편이 가장 안정적입니다.\n"
            "   예: 2024/2024-07 GPS 또는 2024/07\n"
            "\n"
            "2. 장소명은 EXIF GPS가 있어도 오프라인에서는 실제 주소로 바꾸기 어렵습니다.\n"
            "   그래서 앱은 기본적으로 GPS 여부만 폴더명에 반영합니다. 실제 장소명은 나중에 사용자가 폴더명을 바꾸는 방식이 안전합니다.\n"
            "\n"
            "3. 태그는 검색에는 좋지만 파일 시스템만 봐서는 정리 상태가 보이지 않습니다.\n"
            "   장기 보관 목적이면 날짜 폴더를 기준으로 두고, 태그는 보조 메타데이터로 쓰는 방식이 좋습니다.\n"
            "\n"
            "4. 빠른 구조 스캔은 파일을 열지 않고 파일명/작성일/수정일만 봅니다.\n"
            "   촬영 EXIF 날짜와 GPS는 '정밀 날짜 보강'을 눌렀을 때만 읽습니다.\n"
            "\n"
            "5. D드라이브를 검토할 때는 읽기 전용 모드를 유지하세요. 이 모드에서는 이동 실행이 막히고 계획/CSV만 만들 수 있습니다.\n",
        )
        text.configure(state="disabled")

    def _choose_source(self) -> None:
        path = filedialog.askdirectory(title="원본 폴더 또는 드라이브 선택")
        if path:
            self.source_var.set(path)

    def _choose_destination(self) -> None:
        path = filedialog.askdirectory(title="정리 결과를 넣을 폴더 선택")
        if path:
            self.destination_var.set(path)

    def _start_structure_overview(self) -> None:
        source = self.source_var.get().strip()
        if not os.path.isdir(source):
            messagebox.showerror("원본 오류", "존재하는 폴더 또는 드라이브를 선택하세요.")
            return
        self.stop_event.clear()
        self.folders = []
        self.date_audit = []
        self.records = []
        self.plan = []
        self._clear_trees()
        self.status_var.set("구조 개요(구조+용량/종류)를 실행 중입니다.")
        self.worker = threading.Thread(target=self._structure_overview_worker, args=(source,), daemon=True)
        self.worker.start()

    def _structure_overview_worker(self, source: str) -> None:
        engine = PhotoLibraryEngine(lambda text: self.after(0, self.status_var.set, text), self.stop_event)
        folders = engine.scan_folder_structure(source)
        folders = engine.analyze_folder_contents(folders)
        if self.stop_event.is_set():
            self.after(0, self.status_var.set, "구조 개요가 중지되었습니다.")
            return
        self.folders = folders
        self._reindex_folders()
        self.after(0, self._render_folders)
        self.after(0, self.status_var.set, "구조 개요 완료")

    def _start_folder_detail(self) -> None:
        source = self.source_var.get().strip()
        if not os.path.isdir(source):
            messagebox.showerror("원본 오류", "존재하는 폴더 또는 드라이브를 선택하세요.")
            return
        self.stop_event.clear()
        self.folders = []
        self.date_audit = []
        self.records = []
        self.plan = []
        self._clear_trees()
        self.status_var.set("폴더 상세 구조(구조+용량+날짜근거)를 실행 중입니다.")
        self.worker = threading.Thread(target=self._folder_detail_worker, args=(source,), daemon=True)
        self.worker.start()

    def _folder_detail_worker(self, source: str) -> None:
        engine = PhotoLibraryEngine(lambda text: self.after(0, self.status_var.set, text), self.stop_event)
        folders = engine.scan_folder_structure(source)
        folders = engine.analyze_folder_contents(folders)
        roots = [source]
        records: list[DateAuditRecord] = []
        for root in roots:
            records.extend(engine.audit_dates(root, include_metadata=False))
            if self.stop_event.is_set():
                break
        if self.stop_event.is_set():
            self.after(0, self.status_var.set, "폴더 상세 구조가 중지되었습니다.")
            return
        self.folders = folders
        self.date_audit = records
        self._reindex_folders()
        self.after(0, self._render_folders)
        self.after(0, self._render_date_audit)
        self.after(0, self.status_var.set, "폴더 상세 구조 완료")

    def _start_photo_metadata(self) -> None:
        roots = self._selected_scan_roots()
        if not roots:
            messagebox.showinfo("대상 없음", "폴더 구조에서 정리 대상을 먼저 선택하세요.")
            return
        self.stop_event.clear()
        self.records = []
        self.scan_preview_count = 0
        self.scan_tree.delete(*self.scan_tree.get_children())
        self.status_var.set("사진 메타데이터(스캔+EXIF 보강)를 실행 중입니다.")
        self.worker = threading.Thread(target=self._photo_metadata_worker, args=(roots,), daemon=True)
        self.worker.start()

    def _photo_metadata_worker(self, roots: list[str]) -> None:
        engine = PhotoLibraryEngine(lambda text: self.after(0, self.status_var.set, text), self.stop_event)
        records: list[PhotoRecord] = []
        for root in roots:
            records.extend(
                engine.scan(
                    root,
                    include_exif=True,
                    include_fingerprints=False,
                    on_record=lambda batch: self.after(0, self._append_scan_preview, batch),
                )
            )
            if self.stop_event.is_set():
                break
        if self.stop_event.is_set():
            self.after(0, self.status_var.set, "사진 메타데이터 작업이 중지되었습니다.")
            return
        self.records = records
        self.after(0, self.status_var.set, f"사진 메타데이터 완료: {len(records):,}개")

    def _start_filename_duplicate_scan(self) -> None:
        roots = self._selected_scan_roots()
        if not roots:
            messagebox.showinfo("대상 없음", "폴더 구조에서 정리 대상을 먼저 선택하세요.")
            return
        self.stop_event.clear()
        self.clusters = []
        groups: dict[str, list[PhotoRecord]] = {}
        for root in roots:
            for path in iter_photo_paths(root, self.stop_event):
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                name_key = Path(path).name.lower()
                rec = PhotoRecord(
                    path=path,
                    size=stat.st_size,
                    created_at=stat.st_ctime,
                    modified_at=stat.st_mtime,
                    best_date=datetime.fromtimestamp(stat.st_mtime),
                    date_source="수정일",
                    place="Unscanned",
                )
                groups.setdefault(name_key, []).append(rec)
        for name_key, files in groups.items():
            if len(files) > 1:
                self.clusters.append(PhotoCluster("파일명중복", f"name:{name_key}", tuple(sorted(files, key=lambda item: item.path.lower()))))
        self._start_progressive_render_clusters(on_complete=lambda: self.status_var.set(f"파일명 중복 검사 완료: 그룹 {len(self.clusters):,}개"))

    def _start_folder_scan(self) -> None:
        source = self.source_var.get().strip()
        if not os.path.isdir(source):
            messagebox.showerror("원본 오류", "존재하는 폴더 또는 드라이브를 선택하세요.")
            return
        self.stop_event.clear()
        self.folders = []
        self.records = []
        self.date_audit = []
        self.clusters = []
        self.plan = []
        self._clear_trees()
        self.status_var.set("1단계 폴더 구조 파악을 시작합니다. 파일 내용은 열지 않습니다.")
        self.worker = threading.Thread(target=self._folder_scan_worker, args=(source,), daemon=True)
        self.worker.start()

    def _folder_scan_worker(self, source: str) -> None:
        engine = PhotoLibraryEngine(lambda text: self.after(0, self.status_var.set, text), self.stop_event)
        folders = engine.scan_folder_structure(source)
        if self.stop_event.is_set():
            self.after(0, self.status_var.set, "폴더 구조 파악이 중지되었습니다.")
            return
        self.folders = folders
        self._reindex_folders()
        self.after(0, self._render_folders)
        self.after(0, self.summary_var.set, f"폴더 {len(folders):,}개")
        self.after(0, self.status_var.set, "1단계 완료. 다음은 2 용량/종류를 실행하세요.")

    def _start_folder_content_analysis(self) -> None:
        if not self.folders:
            messagebox.showinfo("폴더구조 필요", "먼저 1 폴더구조를 실행하세요.")
            return
        self.stop_event.clear()
        self.status_var.set("2단계 용량/개수/종류 파악을 시작합니다. 파일 내용은 열지 않고 디렉터리 항목만 봅니다.")
        self.worker = threading.Thread(target=self._folder_content_worker, daemon=True)
        self.worker.start()

    def _folder_content_worker(self) -> None:
        engine = PhotoLibraryEngine(lambda text: self.after(0, self.status_var.set, text), self.stop_event)
        folders = engine.analyze_folder_contents(self.folders)
        if self.stop_event.is_set():
            self.after(0, self.status_var.set, "용량/종류 파악이 중지되었습니다.")
            return
        self.folders = folders
        self._reindex_folders()
        self.after(0, self._render_folders)
        total_photos = sum(record.direct_photos for record in folders)
        total_files = sum(record.direct_files for record in folders)
        self.after(0, self.summary_var.set, f"폴더 {len(folders):,}개, 파일 {total_files:,}개, 사진 {total_photos:,}개")
        self.after(0, self.status_var.set, "2단계 완료. 다음은 3 날짜근거 또는 정리 계획을 검토하세요.")

    def _start_date_audit(self) -> None:
        source = self.source_var.get().strip()
        if not os.path.isdir(source):
            messagebox.showerror("원본 오류", "존재하는 폴더 또는 드라이브를 선택하세요.")
            return
        self.stop_event.clear()
        self.date_audit = []
        self.date_tree.delete(*self.date_tree.get_children())
        self.status_var.set("3단계 날짜 근거 파악을 시작합니다. 기본은 메타데이터 없이 파일명/폴더명/수정일만 봅니다.")
        self.worker = threading.Thread(target=self._date_audit_worker, args=(source,), daemon=True)
        self.worker.start()

    def _date_audit_worker(self, source: str) -> None:
        engine = PhotoLibraryEngine(lambda text: self.after(0, self.status_var.set, text), self.stop_event)
        roots = self._selected_scan_roots()
        records: list[DateAuditRecord] = []
        for root in roots:
            records.extend(engine.audit_dates(root, include_metadata=False))
            if self.stop_event.is_set():
                break
        if self.stop_event.is_set():
            self.after(0, self.status_var.set, "날짜 근거 파악이 중지되었습니다.")
            return
        self.date_audit = records
        self.after(0, self._render_date_audit)
        mismatches = sum(1 for record in records if record.status == "불일치")
        self.after(0, self.summary_var.set, f"날짜 검토 {len(records):,}개, 불일치 {mismatches:,}개")
        self.after(0, self.status_var.set, "3단계 완료. 불일치 항목을 우선 검토하세요.")

    def _render_folders(self, expanded_hint: set[str] | None = None, selection_hint: tuple[str, ...] | None = None) -> None:
        if expanded_hint is None:
            expanded_hint = self._snapshot_expanded(self.folder_tree)
        if selection_hint is None:
            selection_hint = self.folder_tree.selection()
        self.folder_tree.delete(*self.folder_tree.get_children())
        sorted_rows = sorted(self.folders, key=lambda item: (item.depth, item.path.lower()))
        mark_cache: dict[str, str] = {}

        def mark_for(path: str) -> str:
            if path in mark_cache:
                return mark_cache[path]
            record = self.folder_map.get(path)
            if not record:
                mark_cache[path] = "☐"
                return "☐"
            children = self.folder_tree_children.get(path, [])
            if not children:
                mark_cache[path] = "☑" if record.include else "☐"
                return mark_cache[path]
            marks = {mark_for(child) for child in children if child in self.folder_map}
            if marks == {"☑"} and record.include:
                mark_cache[path] = "☑"
            elif marks == {"☐"} and not record.include:
                mark_cache[path] = "☐"
            else:
                mark_cache[path] = "▣"
            return mark_cache[path]
        self.folder_state_marks = {record.path: mark_for(record.path) for record in sorted_rows}

        inserted = 0
        for record in sorted_rows:
            parent_id = record.parent if record.parent in self.folder_map else ""
            state_mark = self.folder_state_marks.get(record.path, "☐")
            state_tag = "state_checked" if state_mark == "☑" else ("state_partial" if state_mark == "▣" else "state_unchecked")
            icon = self.icon_checked if state_mark == "☑" else (self.icon_partial if state_mark == "▣" else self.icon_unchecked)
            self.folder_tree.insert(
                parent_id,
                tk.END,
                iid=record.path,
                text=Path(record.path).name or record.path,
                image=icon,
                values=(
                    record.role,
                    record.subfolders,
                    record.total_files,
                    record.total_photos,
                    format_bytes(record.total_bytes),
                    record.extension_summary,
                    record.review_status,
                ),
                tags=(state_tag,),
                open=(record.path in expanded_hint),
            )
            inserted += 1
            if inserted >= MAX_FOLDER_ROWS:
                break
        self._render_selected_summary()
        self._render_excluded_summary()
        still_selected = [item for item in selection_hint if self.folder_tree.exists(item)]
        if still_selected:
            self.folder_tree.selection_set(still_selected)
            self.folder_tree.see(still_selected[0])

    def _render_date_audit(self) -> None:
        self.date_tree.delete(*self.date_tree.get_children())
        rows = sorted(self.date_audit, key=lambda item: (item.status != "불일치", item.path.lower()))
        
        if not hasattr(self, "_date_render_id"):
            self._date_render_id = 0
        self._date_render_id += 1
        
        self._render_date_audit_progressively(rows, 0, self._date_render_id)

    def _render_date_audit_progressively(self, rows: list[DateAuditRecord], start_idx: int, render_id: int) -> None:
        if self.stop_event.is_set():
            return
        if render_id != self._date_render_id:
            return
            
        chunk_size = 150
        max_rows = min(len(rows), MAX_PLAN_PREVIEW_ROWS)
        end_idx = min(start_idx + chunk_size, max_rows)
        
        for index in range(start_idx, end_idx):
            record = rows[index]
            self.date_tree.insert(
                "",
                tk.END,
                values=(
                    record.status,
                    record.filename_date,
                    record.folder_date,
                    record.filesystem_date,
                    record.metadata_date,
                    record.path,
                ),
            )
            
        if end_idx < max_rows:
            self.after(5, self._render_date_audit_progressively, rows, end_idx, render_id)

    def _start_scan(self) -> None:
        roots = self._selected_scan_roots()
        if not roots:
            messagebox.showerror("정리 대상 필요", "폴더 구조에서 정리 대상을 최소 1개 체크하세요.")
            return
        self.stop_event.clear()
        self.records = []
        self.clusters = []
        self.plan = []
        self.scan_preview_count = 0
        self.scan_tree.delete(*self.scan_tree.get_children())
        self.cluster_tree.delete(*self.cluster_tree.get_children())
        self.cluster_files.delete(*self.cluster_files.get_children())
        self.plan_tree.delete(*self.plan_tree.get_children())
        self.plan_review_tree.delete(*self.plan_review_tree.get_children())
        self.status_var.set("빠른 구조 스캔을 시작합니다. 이미지 파일 내용은 열지 않습니다.")
        self.worker = threading.Thread(target=self._scan_worker, args=(roots,), daemon=True)
        self.worker.start()

    def _scan_worker(self, roots: list[str]) -> None:
        engine = PhotoLibraryEngine(lambda text: self.after(0, self.status_var.set, text), self.stop_event)
        records: list[PhotoRecord] = []
        for root in roots:
            records.extend(
                engine.scan(
                    root,
                    include_exif=False,
                    include_fingerprints=False,
                    on_record=lambda batch: self.after(0, self._append_scan_preview, batch),
                )
            )
            if self.stop_event.is_set():
                break
        if self.stop_event.is_set():
            self.after(0, self.status_var.set, "스캔이 중지되었습니다.")
            return
        self.records = records
        self.after(0, self._finish_structure_scan)

    def _finish_structure_scan(self) -> None:
        self.summary_var.set(f"사진 {len(self.records):,}개. 정리 계획을 먼저 만들 수 있습니다.")
        self.status_var.set("빠른 구조 스캔 완료. 필요할 때만 정밀 날짜 보강 또는 중복/유사 분석을 실행하세요.")

    def _append_scan_preview(self, records: list[PhotoRecord]) -> None:
        for record in records:
            self.scan_tree.insert(
                "",
                tk.END,
                values=(
                    record.path,
                    record.best_date.strftime("%Y-%m-%d %H:%M"),
                    record.date_source,
                    format_bytes(record.size),
                ),
            )
            self.scan_preview_count += 1
        children = self.scan_tree.get_children()
        overflow = len(children) - MAX_SCAN_PREVIEW_ROWS
        if overflow > 0:
            self.scan_tree.delete(*children[:overflow])
        self.summary_var.set(f"사진 {self.scan_preview_count:,}개 스캔 중")

    def _start_exif_enrich(self) -> None:
        if not self.records:
            messagebox.showinfo("구조 스캔 필요", "먼저 빠른 구조 스캔으로 사진 목록을 만드세요.")
            return
        self.stop_event.clear()
        self.status_var.set("정밀 날짜 보강을 시작합니다. 이 단계는 사진 파일을 열어서 EXIF를 확인합니다.")
        self.worker = threading.Thread(target=self._exif_enrich_worker, daemon=True)
        self.worker.start()

    def _exif_enrich_worker(self) -> None:
        engine = PhotoLibraryEngine(lambda text: self.after(0, self.status_var.set, text), self.stop_event)
        records = engine.enrich_exif(self.records)
        if self.stop_event.is_set():
            self.after(0, self.status_var.set, "정밀 날짜 보강이 중지되었습니다.")
            return
        self.records = records
        self.after(0, self._finish_exif_enrich)

    def _finish_exif_enrich(self) -> None:
        self.summary_var.set(f"사진 {len(self.records):,}개. EXIF 기준이 반영되었습니다.")
        self.status_var.set("정밀 날짜 보강 완료. 정리 계획을 다시 생성하세요.")

    def _start_duplicate_scan(self) -> None:
        if not self.records:
            messagebox.showinfo("구조 스캔 필요", "먼저 구조 스캔으로 사진 목록을 만드세요.")
            return
        self.stop_event.clear()
        self.clusters = []
        self.cluster_tree.delete(*self.cluster_tree.get_children())
        self.cluster_files.delete(*self.cluster_files.get_children())
        self.status_var.set("중복/유사 분석을 시작합니다. 이 단계는 구조 스캔보다 느립니다.")
        self.telemetry_speed_var.set("0.0 files/s (0.0 MB/s)")
        self.telemetry_eta_var.set("계산 중...")
        self.telemetry_500k_var.set("계산 중...")
        self.worker = threading.Thread(target=self._duplicate_scan_worker, daemon=True)
        self.worker.start()

    def _duplicate_scan_worker(self) -> None:
        def progress_callback(text, telemetry=None):
            self.after(0, self.status_var.set, text)
            if telemetry:
                self.after(0, self.telemetry_speed_var.set, telemetry.get("speed", ""))
                self.after(0, self.telemetry_eta_var.set, telemetry.get("eta", ""))
                self.after(0, self.telemetry_500k_var.set, telemetry.get("extrap_500k", ""))

        engine = PhotoLibraryEngine(progress_callback, self.stop_event, cache_dir=self.source_var.get())
        records = engine.add_fingerprints(self.records)
        if self.stop_event.is_set():
            self.after(0, self.status_var.set, "중복/유사 분석이 중지되었습니다.")
            return
        self.records = records
        self.after(0, self.status_var.set, "중복/유사 그룹을 분류하는 중...")
        clusters = engine.duplicate_clusters(self.records, int(self.threshold_var.get()))
        if self.stop_event.is_set():
            return
        self.clusters = clusters
        self.after(0, self._start_progressive_render_clusters)

    def _delete_db_cache(self) -> None:
        if not messagebox.askyesno("캐시 삭제 확인", "정말로 데이터베이스 캐시를 삭제하시겠습니까?\n삭제 후에는 중복/유사 분석 시 모든 이미지 지문을 처음부터 다시 계산해야 합니다."):
            return
        
        source_dir = self.source_var.get()
        if not source_dir:
            messagebox.showerror("오류", "선택된 소스 디렉토리가 없습니다.")
            return
            
        db_path = Path(source_dir) / ".photos-data" / "photos_gui_cache.db"
        if db_path.exists():
            try:
                db_path.unlink()
                messagebox.showinfo("캐시 삭제 완료", "데이터베이스 캐시 파일이 성공적으로 삭제되었습니다.")
            except Exception as e:
                messagebox.showerror("오류", f"캐시 파일을 삭제하는 중 오류가 발생했습니다:\n{e}")
        else:
            messagebox.showinfo("캐시 없음", "삭제할 데이터베이스 캐시 파일이 존재하지 않습니다.")
            
        self.telemetry_speed_var.set("0.0 files/s (0.0 MB/s)")
        self.telemetry_eta_var.set("대기 중")
        self.telemetry_500k_var.set("대기 중")

    def _stop(self) -> None:
        self.stop_event.set()
        self.status_var.set("중지 요청을 보냈습니다.")

    def _refresh_clusters(self) -> None:
        if not self.records:
            return
        if hasattr(self, "_refresh_debounce_timer") and self._refresh_debounce_timer:
            try:
                self.after_cancel(self._refresh_debounce_timer)
            except Exception:
                pass
            self._refresh_debounce_timer = None
            
        self._refresh_debounce_timer = self.after(300, self._run_refresh_clusters_thread)

    def _run_refresh_clusters_thread(self) -> None:
        self._refresh_debounce_timer = None
        self.status_var.set("유사도 변경 반영 중...")
        
        def run_thread():
            engine = PhotoLibraryEngine(lambda text: self.after(0, self.status_var.set, text), self.stop_event)
            clusters = engine.duplicate_clusters(self.records, int(self.threshold_var.get()))
            if self.stop_event.is_set():
                return
            self.clusters = clusters
            self.after(0, self._start_progressive_render_clusters)
            
        self._cluster_thread = threading.Thread(target=run_thread, daemon=True)
        self._cluster_thread.start()

    def _start_progressive_render_clusters(self, on_complete=None) -> None:
        self.cluster_tree.delete(*self.cluster_tree.get_children())
        self.cluster_files.delete(*self.cluster_files.get_children())
        if not hasattr(self, "_cluster_render_id"):
            self._cluster_render_id = 0
        self._cluster_render_id += 1
        self._render_clusters_progressively(0, self._cluster_render_id, on_complete)

    def _render_clusters_progressively(self, start_idx: int, render_id: int, on_complete=None) -> None:
        if self.stop_event.is_set():
            return
        if render_id != self._cluster_render_id:
            return
        
        chunk_size = 100
        end_idx = min(start_idx + chunk_size, len(self.clusters))
        
        for index in range(start_idx, end_idx):
            cluster = self.clusters[index]
            self.cluster_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(cluster.kind, len(cluster.files), cluster.score)
            )
            
        if end_idx < len(self.clusters):
            self.after(5, self._render_clusters_progressively, end_idx, render_id, on_complete)
        else:
            if on_complete:
                on_complete()
            else:
                self.summary_var.set(f"사진 {len(self.records):,}개, 중복/유사 그룹 {len(self.clusters):,}개")
                self.status_var.set("분석 완료")

    def _show_cluster_files(self, _event=None) -> None:
        self.cluster_files.delete(*self.cluster_files.get_children())
        selection = self.cluster_tree.selection()
        if not selection:
            return
        cluster = self.clusters[int(selection[0])]
        for record in cluster.files:
            self.cluster_files.insert(
                "",
                tk.END,
                values=(record.path, record.best_date.strftime("%Y-%m-%d %H:%M"), format_bytes(record.size)),
            )

    def _build_plan(self) -> None:
        destination = self.destination_var.get().strip()
        if not self.records:
            messagebox.showinfo("스캔 필요", "먼저 4 사진스캔을 실행하세요.")
            return
        if not destination:
            messagebox.showwarning("대상 폴더 필요", "정리 대상 폴더를 선택하세요.")
            return
        engine = PhotoLibraryEngine(lambda text: self.status_var.set(text), self.stop_event)
        self.plan = engine.build_organize_plan(self.records, destination, self.mode_var.get(), self.plan_scheme_var.get())
        self._render_plan_tree()
        extra = len(self.plan) - min(len(self.plan), MAX_PLAN_PREVIEW_ROWS)
        suffix = f" 표에는 처음 {MAX_PLAN_PREVIEW_ROWS:,}건만 표시됩니다." if extra > 0 else ""
        self._save_plan_files()
        self.status_var.set(f"정리 계획 {len(self.plan):,}건 생성. 읽기 전용이면 실행은 막힙니다.{suffix}")

    def _execute_plan(self) -> None:
        if self.read_only_var.get():
            messagebox.showwarning("읽기 전용", "읽기 전용 모드에서는 파일을 이동하지 않습니다.")
            return
        if not self.plan:
            messagebox.showinfo("계획 없음", "먼저 정리 계획을 생성하세요.")
            return
        if not messagebox.askyesno("파일 이동 확인", f"{len(self.plan):,}개 파일을 실제로 이동할까요?"):
            return
        if not messagebox.askyesno("최종 확인", "실제 이동을 진행합니다. 계속할까요?"):
            return
        self._run_dry_run()
        if "오류 0건" not in self.status_var.get():
            return
        
        self.stop_event.clear()
        self.status_var.set("파일 이동을 준비 중입니다...")
        
        self.worker = threading.Thread(target=self._execute_plan_worker, daemon=True)
        self.worker.start()

    def _execute_plan_worker(self) -> None:
        moved = 0
        review_root = self._review_root()
        try:
            review_root.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self.after(0, messagebox.showerror, "폴더 생성 오류", f"검수 루트 폴더를 생성할 수 없습니다: {exc}")
            self.after(0, self.status_var.set, f"오류 발생: {exc}")
            return

        log_path = review_root / "execution_log.csv"
        undo_path = review_root / "undo_plan.csv"
        log_rows = []
        undo_rows = []
        
        total_files = len(self.plan)
        
        for idx, action in enumerate(self.plan, start=1):
            if self.stop_event.is_set():
                self.after(0, self.status_var.set, f"이동 중단됨. 완료: {moved}/{total_files}개")
                break
                
            try:
                Path(action.destination).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(action.source, action.destination)
                moved += 1
                log_rows.append((action.source, action.destination, "moved", datetime.now().isoformat()))
                undo_rows.append((action.destination, action.source))
            except OSError as exc:
                log_rows.append((action.source, action.destination, f"failed:{exc}", datetime.now().isoformat()))
                
            if idx % 50 == 0 or idx == total_files:
                self.after(0, self.status_var.set, f"파일 이동 중... {idx}/{total_files} ({moved}개 성공)")
                
        try:
            with open(log_path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(["source", "destination", "result", "timestamp"])
                writer.writerows(log_rows)
            with open(undo_path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(["moved_path", "restore_to"])
                writer.writerows(undo_rows)
        except Exception as exc:
            self.after(0, self.status_var.set, f"로그 작성 중 오류: {exc}")
            return
            
        if self.stop_event.is_set():
            self.after(0, self.status_var.set, f"파일 {moved:,}개 이동 후 중단됨 (로그 기록 완료)")
        else:
            self.after(0, self.status_var.set, f"파일 {moved:,}개 이동 완료")

    def _export_clusters(self) -> None:
        if not self.clusters:
            messagebox.showinfo("결과 없음", "저장할 중복/유사 결과가 없습니다.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=(("CSV files", "*.csv"),))
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["group", "kind", "score", "path", "date", "size", "sha256"])
            for index, cluster in enumerate(self.clusters, start=1):
                for record in cluster.files:
                    writer.writerow([index, cluster.kind, cluster.score, record.path, record.best_date, record.size, record.sha256])
        self.status_var.set(f"CSV 저장 완료: {path}")

    def _export_plan(self) -> None:
        if not self.plan:
            messagebox.showinfo("계획 없음", "저장할 정리 계획이 없습니다.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=(("CSV files", "*.csv"),))
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["source", "destination", "date_reason"])
            for action in self.plan:
                writer.writerow([action.source, action.destination, action.reason])
        self.status_var.set(f"계획 CSV 저장 완료: {path}")

    def _review_root(self) -> Path:
        return Path(self.destination_var.get().strip() or "D:\\PICTURES") / REVIEW_DIR_NAME

    def _reindex_folders(self) -> None:
        self.folder_map = {record.path: record for record in self.folders}
        children: dict[str, list[str]] = {}
        for record in self.folders:
            children.setdefault(record.parent, []).append(record.path)
        self.folder_tree_children = children

    def _toggle_folder_include_by_path(self, target: str) -> None:
        if target not in self.folder_map:
            return
        expanded = self._snapshot_expanded(self.folder_tree)
        selected = self.folder_tree.selection()
        new_value = not self.folder_map[target].include
        self._set_include_recursive(target, new_value)
        self._apply_parent_partial_state(target)
        self._render_folders(expanded_hint=expanded, selection_hint=selected)

    def _snapshot_expanded(self, tree: ttk.Treeview) -> set[str]:
        expanded: set[str] = set()

        def walk(parent: str = "") -> None:
            for child in tree.get_children(parent):
                if tree.item(child, "open"):
                    expanded.add(child)
                    walk(child)

        walk("")
        return expanded

    def _on_folder_tree_click(self, event) -> None:
        row_id = self.folder_tree.identify_row(event.y)
        if not row_id:
            return
        column = self.folder_tree.identify_column(event.x)
        element = self.folder_tree.identify("element", event.x, event.y)
        if element == "Treeitem.indicator":
            return
        if column == "#0" and element in {"Treeitem.image", "image"}:
            self._toggle_folder_include_by_path(row_id)

    def _on_folder_tree_right_click(self, event) -> None:
        row_id = self.folder_tree.identify_row(event.y)
        if not row_id:
            return
        self.folder_tree.selection_set(row_id)
        self._menu_target_path = row_id
        self.folder_menu.tk_popup(event.x_root, event.y_root)

    def _on_selected_tree_right_click(self, event) -> None:
        row_id = self.selected_tree.identify_row(event.y)
        if not row_id:
            return
        self.selected_tree.selection_set(row_id)
        self._menu_target_path = row_id
        self.folder_menu.tk_popup(event.x_root, event.y_root)

    def _on_excluded_tree_right_click(self, event) -> None:
        row_id = self.excluded_tree.identify_row(event.y)
        if not row_id:
            return
        self.excluded_tree.selection_set(row_id)
        self._menu_target_path = row_id
        self.folder_menu.tk_popup(event.x_root, event.y_root)

    def _set_include_recursive(self, path: str, include: bool) -> None:
        record = self.folder_map.get(path)
        if not record:
            return
        record.include = include
        for child in self.folder_tree_children.get(path, []):
            self._set_include_recursive(child, include)

    def _apply_parent_partial_state(self, path: str) -> None:
        current = self.folder_map.get(path)
        while current and current.parent:
            parent = self.folder_map.get(current.parent)
            if not parent:
                break
            child_paths = self.folder_tree_children.get(parent.path, [])
            includes = [self.folder_map[child].include for child in child_paths if child in self.folder_map]
            if includes and all(includes):
                parent.include = True
                if parent.review_status == "부분선택":
                    parent.review_status = ""
            elif includes and not any(includes):
                parent.include = False
                if parent.review_status == "부분선택":
                    parent.review_status = ""
            else:
                parent.include = False
                parent.review_status = "부분선택"
            current = parent

    def _render_selected_summary(self) -> None:
        self.selected_tree.delete(*self.selected_tree.get_children())
        roots = self._selected_scan_roots()
        for root in roots:
            record = self.folder_map.get(root)
            if not record:
                continue
            mark = self.folder_state_marks.get(root, "☑")
            icon = self.icon_checked if mark == "☑" else (self.icon_partial if mark == "▣" else self.icon_unchecked)
            node = self.selected_tree.insert(
                "",
                tk.END,
                iid=root,
                text=Path(root).name or root,
                image=icon,
                values=(record.total_files, record.total_photos, format_bytes(record.total_bytes)),
            )
            for child in self.folder_tree_children.get(root, []):
                child_record = self.folder_map.get(child)
                if not child_record or not child_record.include:
                    continue
                child_mark = self.folder_state_marks.get(child, "☑")
                child_icon = self.icon_checked if child_mark == "☑" else (self.icon_partial if child_mark == "▣" else self.icon_unchecked)
                self.selected_tree.insert(
                    node,
                    tk.END,
                    iid=child,
                    text=Path(child).name or child,
                    image=child_icon,
                    values=(child_record.total_files, child_record.total_photos, format_bytes(child_record.total_bytes)),
                )

    def _render_excluded_summary(self) -> None:
        self.excluded_tree.delete(*self.excluded_tree.get_children())
        if not self.folders:
            return
        candidates = [record.path for record in self.folders if not record.include and record.depth > 0]
        candidates.sort(key=lambda item: (len(item), item.lower()))
        roots: list[str] = []
        for path in candidates:
            if any(path.startswith(existing + os.sep) or path == existing for existing in roots):
                continue
            roots.append(path)
        for root in roots:
            record = self.folder_map.get(root)
            if not record:
                continue
            mark = self.folder_state_marks.get(root, "☐")
            icon = self.icon_checked if mark == "☑" else (self.icon_partial if mark == "▣" else self.icon_unchecked)
            node = self.excluded_tree.insert(
                "",
                tk.END,
                iid=root,
                text=Path(root).name or root,
                image=icon,
                values=(record.total_files, record.total_photos, format_bytes(record.total_bytes)),
            )
            for child in self.folder_tree_children.get(root, []):
                child_record = self.folder_map.get(child)
                if not child_record or child_record.include:
                    continue
                child_mark = self.folder_state_marks.get(child, "☐")
                child_icon = self.icon_checked if child_mark == "☑" else (self.icon_partial if child_mark == "▣" else self.icon_unchecked)
                self.excluded_tree.insert(
                    node,
                    tk.END,
                    iid=child,
                    text=Path(child).name or child,
                    image=child_icon,
                    values=(child_record.total_files, child_record.total_photos, format_bytes(child_record.total_bytes)),
                )

    def _on_selected_tree_click(self, event) -> None:
        row_id = self.selected_tree.identify_row(event.y)
        if not row_id:
            return
        column = self.selected_tree.identify_column(event.x)
        element = self.selected_tree.identify("element", event.x, event.y)
        if element == "Treeitem.indicator":
            return
        if column == "#0" and element in {"Treeitem.image", "image"}:
            self._toggle_folder_include_by_path(row_id)

    def _on_excluded_tree_click(self, event) -> None:
        row_id = self.excluded_tree.identify_row(event.y)
        if not row_id:
            return
        column = self.excluded_tree.identify_column(event.x)
        element = self.excluded_tree.identify("element", event.x, event.y)
        if element == "Treeitem.indicator":
            return
        if column == "#0" and element in {"Treeitem.image", "image"}:
            self._toggle_folder_include_by_path(row_id)

    def _menu_open_in_explorer(self) -> None:
        target = self._menu_target_path
        if not target:
            return
        if os.path.isdir(target):
            os.startfile(target)
        elif os.path.exists(target):
            subprocess.run(["explorer", "/select,", target], check=False)

    def _menu_focus_left(self) -> None:
        target = self._menu_target_path
        if not target or not self.folder_tree.exists(target):
            return
        current = target
        while True:
            parent = self.folder_map.get(current).parent if self.folder_map.get(current) else ""
            if not parent or not self.folder_tree.exists(parent):
                break
            self.folder_tree.item(parent, open=True)
            current = parent
        self.folder_tree.selection_set(target)
        self.folder_tree.see(target)
        self.folder_tree.focus(target)

    def _menu_include_target(self) -> None:
        self._menu_set_target(include=True, recursive=False)

    def _menu_exclude_target(self) -> None:
        self._menu_set_target(include=False, recursive=False)

    def _menu_include_subtree(self) -> None:
        self._menu_set_target(include=True, recursive=True)

    def _menu_exclude_subtree(self) -> None:
        self._menu_set_target(include=False, recursive=True)

    def _menu_copy_path(self) -> None:
        target = self._menu_target_path
        if not target:
            return
        self.clipboard_clear()
        self.clipboard_append(target)
        self.status_var.set(f"경로 복사: {target}")

    def _menu_set_target(self, include: bool, recursive: bool) -> None:
        target = self._menu_target_path
        if not target or target not in self.folder_map:
            return
        expanded = self._snapshot_expanded(self.folder_tree)
        selected = self.folder_tree.selection()
        if recursive:
            self._set_include_recursive(target, include)
        else:
            self.folder_map[target].include = include
        self._apply_parent_partial_state(target)
        self._render_folders(expanded_hint=expanded, selection_hint=selected)

    def _selected_scan_roots(self) -> list[str]:
        if not self.folders:
            source = self.source_var.get().strip()
            return [source] if source and os.path.isdir(source) else []
        selected = [record.path for record in self.folders if record.include and record.depth > 0]
        selected.sort(key=lambda item: (len(item), item.lower()))
        roots: list[str] = []
        for path in selected:
            if any(path.startswith(existing + os.sep) or path == existing for existing in roots):
                continue
            roots.append(path)
        return roots

    def _render_plan_tree(self) -> None:
        self.plan_tree.delete(*self.plan_tree.get_children())
        root = self.destination_var.get().strip() or "D:\\PICTURES"
        size_map = {r.path: r.size for r in self.records}
        agg: dict[str, tuple[int, int, str]] = {}
        for action in self.plan:
            destination = Path(action.destination)
            bytes_size = size_map.get(action.source, 0)
            agg[str(destination)] = (1, bytes_size, action.reason)
            parent = destination.parent
            while str(parent).lower().startswith(root.lower()):
                existing = agg.get(str(parent), (0, 0, action.reason))
                agg[str(parent)] = (existing[0] + 1, existing[1] + bytes_size, existing[2])
                if str(parent).lower() == root.lower():
                    break
                parent = parent.parent

        nodes = sorted(agg.keys(), key=lambda item: (item.count("\\") if "\\" in item else 0, item.lower()))
        for path in nodes:
            parent = str(Path(path).parent)
            parent_id = parent if parent in agg else ""
            count, size, reason = agg[path]
            label = Path(path).name or path
            self.plan_tree.insert(parent_id, tk.END, iid=path, text=label, values=(count, format_bytes(size), reason))
        self._render_plan_review(root, size_map)

    def _render_plan_review(self, root: str, size_map: dict[str, int] | None = None) -> None:
        self.plan_review_tree.delete(*self.plan_review_tree.get_children())
        total_files = len(self.plan)
        if size_map is None:
            size_map = {r.path: r.size for r in self.records}
        total_bytes = sum(size_map.get(action.source, 0) for action in self.plan)

        mismatches = sum(1 for row in self.date_audit if row.status == "불일치")
        metadata_missing = sum(1 for row in self.date_audit if row.metadata_date in {"", "미확인"})
        duplicate_groups = len(self.clusters)

        summary = self.plan_review_tree.insert("", tk.END, text="요약", values=("",))
        self.plan_review_tree.insert(summary, tk.END, text="정리 파일 수", values=(f"{total_files:,}",))
        self.plan_review_tree.insert(summary, tk.END, text="정리 용량", values=(format_bytes(total_bytes),))
        self.plan_review_tree.insert(summary, tk.END, text="목표 루트", values=(root,))

        criteria = self.plan_review_tree.insert("", tk.END, text="기준", values=("",))
        self.plan_review_tree.insert(criteria, tk.END, text="날짜 소스 모드", values=(self.mode_var.get(),))
        self.plan_review_tree.insert(criteria, tk.END, text="구조 스키마", values=(self.plan_scheme_var.get(),))
        self.plan_review_tree.insert(criteria, tk.END, text="읽기 전용", values=("ON" if self.read_only_var.get() else "OFF",))

        risks = self.plan_review_tree.insert("", tk.END, text="주의 항목", values=("",))
        self.plan_review_tree.insert(risks, tk.END, text="날짜 불일치", values=(f"{mismatches:,}",))
        self.plan_review_tree.insert(risks, tk.END, text="메타 미확인", values=(f"{metadata_missing:,}",))
        self.plan_review_tree.insert(risks, tk.END, text="중복/유사 그룹", values=(f"{duplicate_groups:,}",))

        samples = self.plan_review_tree.insert("", tk.END, text="샘플 경로", values=("",))
        for action in self.plan[:20]:
            self.plan_review_tree.insert(samples, tk.END, text=Path(action.destination).name, values=(action.destination,))
        self.plan_review_tree.item(summary, open=True)
        self.plan_review_tree.item(criteria, open=True)
        self.plan_review_tree.item(risks, open=True)

    def _export_review_bundle(self) -> None:
        review_root = self._review_root()
        review_root.mkdir(parents=True, exist_ok=True)
        folder_csv = review_root / "folder_inventory.csv"
        folder_json = review_root / "folder_inventory.json"
        date_csv = review_root / "date_audit.csv"
        date_json = review_root / "date_audit.json"
        draft_json = review_root / "organize_draft.json"
        review_json = review_root / "composite_review.json"
        with open(folder_csv, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["path", "include", "role", "review_status", "depth", "files", "photos", "bytes", "extensions"])
            for record in self.folders:
                writer.writerow([record.path, record.include, record.role, record.review_status, record.depth, record.total_files, record.total_photos, record.total_bytes, record.extension_summary])
        with open(folder_json, "w", encoding="utf-8") as file:
            json.dump([record.__dict__ for record in self.folders], file, ensure_ascii=False, indent=2)
        with open(date_csv, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["path", "status", "filename_date", "folder_date", "filesystem_date", "metadata_date"])
            for record in self.date_audit:
                writer.writerow([record.path, record.status, record.filename_date, record.folder_date, record.filesystem_date, record.metadata_date])
        with open(date_json, "w", encoding="utf-8") as file:
            json.dump([record.__dict__ for record in self.date_audit], file, ensure_ascii=False, indent=2)
        with open(draft_json, "w", encoding="utf-8") as file:
            json.dump({"root": self.source_var.get().strip(), "destination_root": self.destination_var.get().strip(), "selected_scan_roots": self._selected_scan_roots()}, file, ensure_ascii=False, indent=2)
        duplicate_map: dict[str, dict[str, object]] = {}
        for cluster in self.clusters:
            for record in cluster.files:
                duplicate_map[record.path] = {"cluster_kind": cluster.kind, "score": cluster.score, "count": len(cluster.files)}
        date_map = {record.path: record for record in self.date_audit}
        composite = []
        for record in self.records:
            folder = str(Path(record.path).parent)
            folder_record = self.folder_map.get(folder)
            date_record = date_map.get(record.path)
            dup = duplicate_map.get(record.path)
            composite.append(
                {
                    "path": record.path,
                    "folder": folder,
                    "folder_included": folder_record.include if folder_record else None,
                    "folder_role": folder_record.role if folder_record else "",
                    "best_date": record.best_date.strftime("%Y-%m-%d %H:%M:%S"),
                    "date_source": record.date_source,
                    "filename_folder_filesystem_match": date_record.status if date_record else "",
                    "filename_date": date_record.filename_date if date_record else "",
                    "folder_date": date_record.folder_date if date_record else "",
                    "filesystem_date": date_record.filesystem_date if date_record else "",
                    "metadata_date": date_record.metadata_date if date_record else "",
                    "duplicate_kind": dup["cluster_kind"] if dup else "",
                    "duplicate_group_size": dup["count"] if dup else 0,
                }
            )
        with open(review_json, "w", encoding="utf-8") as file:
            json.dump(composite, file, ensure_ascii=False, indent=2)
        self.status_var.set(f"Review 파일 저장 완료: {review_root}")

    def _load_codex_review(self) -> None:
        review_file = self._review_root() / "codex_review.json"
        if not review_file.exists():
            messagebox.showinfo("Review 파일 없음", f"{review_file} 파일이 없습니다.")
            return
        try:
            with open(review_file, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Review 로드 실패", str(exc))
            return

        decisions = payload.get("folder_decisions", [])
        path_map = {record.path.lower(): record for record in self.folders}
        for item in decisions:
            path = str(item.get("path", "")).lower()
            record = path_map.get(path)
            if not record:
                continue
            if "include" in item:
                record.include = bool(item["include"])
            if item.get("role"):
                record.role = str(item["role"])
            record.review_status = "검수반영"
        self._reindex_folders()
        self._render_folders()
        self.status_var.set("codex_review.json 반영 완료")

    def _run_dry_run(self) -> None:
        if not self.plan:
            messagebox.showinfo("계획 없음", "먼저 정리 계획을 생성하세요.")
            return
        destination_root = Path(self.destination_var.get().strip() or "D:\\PICTURES").resolve()
        errors: list[str] = []
        seen_destinations: set[str] = set()
        for action in self.plan:
            try:
                src = Path(action.source).resolve()
                dst = Path(action.destination).resolve()
            except OSError:
                errors.append(f"경로 확인 실패: {action.source}")
                continue
            if not str(dst).lower().startswith(str(destination_root).lower()):
                errors.append(f"대상 루트 이탈: {dst}")
            if is_excluded_folder(str(src.parent)):
                errors.append(f"제외 후보 포함: {src}")
            if str(dst).lower() in seen_destinations:
                errors.append(f"대상 충돌: {dst}")
            seen_destinations.add(str(dst).lower())
        if errors:
            preview = "\n".join(errors[:10])
            messagebox.showwarning("Dry-run 실패", f"오류 {len(errors)}건\n{preview}")
            self.status_var.set(f"Dry-run 실패: 오류 {len(errors)}건")
        else:
            self.status_var.set("Dry-run 통과: 오류 0건")

    def _open_selected_cluster_file(self, _event=None) -> None:
        selection = self.cluster_files.selection()
        if not selection:
            return
        path = self.cluster_files.item(selection[0], "values")[0]
        if os.path.exists(path):
            os.startfile(path)

    def _clear_trees(self) -> None:
        self.folder_tree.delete(*self.folder_tree.get_children())
        self.selected_tree.delete(*self.selected_tree.get_children())
        self.excluded_tree.delete(*self.excluded_tree.get_children())
        self.date_tree.delete(*self.date_tree.get_children())
        self.scan_tree.delete(*self.scan_tree.get_children())
        self.cluster_tree.delete(*self.cluster_tree.get_children())
        self.cluster_files.delete(*self.cluster_files.get_children())
        self.plan_tree.delete(*self.plan_tree.get_children())

    def _save_plan_files(self) -> None:
        review_root = self._review_root()
        review_root.mkdir(parents=True, exist_ok=True)
        csv_path = review_root / "organize_plan.csv"
        json_path = review_root / "organize_plan.json"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["source", "destination", "reason"])
            for action in self.plan:
                writer.writerow([action.source, action.destination, action.reason])
        with open(json_path, "w", encoding="utf-8") as file:
            json.dump([{"source": action.source, "destination": action.destination, "reason": action.reason} for action in self.plan], file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    app = PhotoOrganizerApp()
    app.mainloop()
