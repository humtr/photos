import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
VENDOR_DIR = APP_DIR / "vendor"
SRC_DIR = APP_DIR / "src"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))
if SRC_DIR.exists():
    sys.path.insert(1 if VENDOR_DIR.exists() else 0, str(SRC_DIR))

from photos.services import PhotoOrganizerService
from photos.recovery_text import summarize_service_failure

try:
    from PIL import ExifTags, Image, ImageTk
except Exception as exc:  # pragma: no cover - shown in GUI at runtime
    Image = None
    ImageTk = None
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
COMPOSITE_REVIEW_CHUNK_SIZE = 50000
DATE_PATTERNS = (
    re.compile(r"(?P<year>20\d{2}|19\d{2})[-_. ]?(?P<month>0[1-9]|1[0-2])[-_. ]?(?P<day>0[1-9]|[12]\d|3[01])"),
    re.compile(r"(?P<year>20\d{2}|19\d{2})[-_. ]?(?P<month>[1-9])[-_. ]?(?P<day>[1-9]|[12]\d|3[01])"),
)
EXIF_DATE_TAGS = ("DateTimeOriginal", "DateTimeDigitized", "DateTime")
DATE_STATUS_PRIORITY = {
    "자동 수정 금지": 0,
    "강한 불일치": 1,
    "검토 필요": 2,
    "메타데이터 없음": 3,
    "정상": 4,
}


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


def parse_review_date(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def classify_date_status(
    filename_date: datetime | None,
    folder_date: datetime | None,
    filesystem_date: datetime,
    metadata_date: datetime | None,
    include_metadata: bool,
) -> str:
    known_dates = [value for value in (filename_date, folder_date, filesystem_date, metadata_date) if value]
    if not known_dates:
        return "정상"

    years = {value.year for value in known_dates}
    month_days = {(value.month, value.day) for value in known_dates}

    if (
        len(years) > 1
        and filename_date
        and folder_date
        and metadata_date
        and len({filename_date.year, folder_date.year, metadata_date.year}) > 1
    ):
        return "자동 수정 금지"
    if len(years) > 1:
        return "강한 불일치"
    if len(month_days) > 1:
        return "검토 필요"
    if include_metadata and not metadata_date:
        return "메타데이터 없음"
    return "정상"


def safe_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]+', "_", value.strip())
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .") or "Unknown"


def sanitize_filename_suggestion(name: str, fallback_name: str) -> str:
    base = safe_name(Path(name).name)
    if not base:
        return Path(fallback_name).name
    # Keep automatic rename conservative: ASCII only.
    if any(ord(ch) > 127 for ch in base):
        return Path(fallback_name).name
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip(" .")
    return cleaned or Path(fallback_name).name


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
    def __init__(self, on_progress, stop_event: threading.Event):
        self.on_progress = on_progress
        self.stop_event = stop_event

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

            status = classify_date_status(filename_date, folder_date, filesystem_date, metadata_date, include_metadata)
            results.append(
                DateAuditRecord(
                    path=path,
                    filename_date=filename_date.strftime("%Y-%m-%d") if filename_date else "",
                    folder_date=folder_date.strftime("%Y-%m-%d") if folder_date else "",
                    filesystem_date=filesystem_date.strftime("%Y-%m-%d"),
                    metadata_date=metadata_date.strftime("%Y-%m-%d") if metadata_date else ("미확인" if include_metadata else ""),
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
        fingerprinted = []
        for index, record in enumerate(records, start=1):
            if self.stop_event.is_set():
                return fingerprinted
            try:
                sha256 = record.sha256 or sha256_file(record.path)
                phash = record.phash or image_phash(record.path)
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
            if index % 10 == 0:
                self.on_progress(f"중복/유사 분석: 이미지 지문 {index:,}/{len(records):,}개 계산 중")
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
        self.scan_preview_count = 0

        self.folders: list[FolderRecord] = []
        self.folder_map: dict[str, FolderRecord] = {}
        self.folder_tree_children: dict[str, list[str]] = {}
        self.folder_state_marks: dict[str, str] = {}
        self.date_audit: list[DateAuditRecord] = []
        self.records: list[PhotoRecord] = []
        self.duplicate_records: list[PhotoRecord] = []
        self.clusters: list[PhotoCluster] = []
        self.filename_duplicates: dict[str, list[str]] = {}
        self.plan: list[OrganizeAction] = []
        self.review_date_overrides: dict[str, datetime] = {}
        self.review_rename_suggestions: dict[str, str] = {}
        self.review_folder_rename_suggestions: dict[str, str] = {}
        self.review_duplicate_candidates: list[dict[str, object]] = []
        self.review_notes: list[str] = []
        self.review_metadata_suggestions: list[dict[str, object]] = []
        self.bulk_suggestions: list[dict[str, object]] = []
        self.scan_filter_status_var = tk.StringVar(value="all")
        self.scan_filter_extension_var = tk.StringVar(value="all")
        self.scan_filter_duplicate_candidate_only_var = tk.BooleanVar(value=False)
        self.scan_filter_excluded_only_var = tk.BooleanVar(value=False)
        self.duplicate_scope_var = tk.StringVar(value="selected_roots")
        self.duplicate_candidate_pair_var = tk.StringVar(value="all")
        self.preview_image_ref: tk.PhotoImage | None = None
        self.has_folder_inventory = False
        self.has_date_audit = False
        self.has_photo_records = False
        self.has_duplicate_scan = False
        self.workflow_steps: list[tuple[str, str]] = [
            ("step1", "1 구조 개요"),
            ("step2", "2 폴더 상세 구조"),
            ("step3", "3 날짜 근거"),
            ("step4", "4 사진 메타데이터"),
            ("step5", "5 파일명 중복검사"),
            ("step6", "6 Review 저장"),
        ]
        self.workflow_completed: dict[str, bool] = {key: False for key, _ in self.workflow_steps}
        self.workflow_selection: dict[str, bool] = {key: False for key, _ in self.workflow_steps}
        self.workflow_queue: list[str] = []
        self.workflow_running = False
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None

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
            # Keep column-resize enabled; only block heading-click side effects.
            if region == "heading":
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
        ttk.Button(header, text="선택 실행", command=self._run_selected_workflow).grid(row=0, column=3, padx=(8, 0))
        ttk.Button(header, text="Review 로드", command=self._load_codex_review).grid(row=0, column=4, padx=(8, 0))
        ttk.Button(header, text="Dry-run", command=self._run_dry_run).grid(row=0, column=5, padx=(8, 0))
        ttk.Button(header, text="중지", command=self._stop).grid(row=0, column=6, padx=(8, 0))

        checklist_wrap = ttk.Frame(header)
        checklist_wrap.grid(row=1, column=0, columnspan=7, sticky="ew", pady=(8, 0))
        checklist_wrap.columnconfigure(0, weight=1)
        self.workflow_tree = ttk.Treeview(checklist_wrap, columns=("state", "step"), show="headings", height=2)
        self.workflow_tree.heading("state", text="상태")
        self.workflow_tree.heading("step", text="작업")
        self.workflow_tree.column("state", width=140, anchor=tk.W)
        self.workflow_tree.column("step", width=840, anchor=tk.W)
        self.workflow_tree.grid(row=0, column=0, sticky="ew")
        self.workflow_tree.tag_configure("done", foreground="#8a8f98")
        self.workflow_tree.tag_configure("active", foreground="#111111")
        self.workflow_tree.bind("<Button-1>", self._on_workflow_click)
        self._lock_tree_header_drag(self.workflow_tree)
        self._render_workflow_tree()

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
            text="파일명/폴더명/수정일/메타데이터 날짜를 비교해 정상, 검토 필요, 강한 불일치, 자동 수정 금지로 분류합니다.",
        ).grid(row=0, column=0, sticky="w")

        split = ttk.PanedWindow(self.date_tab, orient=tk.HORIZONTAL)
        split.grid(row=1, column=0, sticky="nsew")
        left = ttk.Frame(split)
        right = ttk.Frame(split)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        split.add(left, weight=3)
        split.add(right, weight=2)

        self.date_tree = ttk.Treeview(
            left,
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
        self.date_tree.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.date_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.date_tree.configure(yscrollcommand=scroll.set)
        self._lock_tree_header_drag(self.date_tree)

        actions = ttk.Frame(right)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(actions, text="일괄 제안 생성", command=self._generate_bulk_suggestions).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="제안 반영", command=self._apply_bulk_suggestions).grid(row=0, column=1)
        ttk.Button(actions, text="메타 계획 저장", command=self._export_metadata_edit_plan).grid(row=0, column=2, padx=(8, 0))

        self.bulk_tree = ttk.Treeview(
            right,
            columns=("apply", "kind", "current", "proposed", "path"),
            show="headings",
        )
        for column, label, width in (
            ("apply", "적용", 60),
            ("kind", "유형", 100),
            ("current", "현재", 140),
            ("proposed", "제안", 140),
            ("path", "대상", 320),
        ):
            self.bulk_tree.heading(column, text=label)
            self.bulk_tree.column(column, width=width, anchor=tk.W)
        self.bulk_tree.grid(row=1, column=0, sticky="nsew")
        self.bulk_tree.bind("<Button-1>", self._on_bulk_tree_click)
        bulk_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.bulk_tree.yview)
        bulk_scroll.grid(row=1, column=1, sticky="ns")
        self.bulk_tree.configure(yscrollcommand=bulk_scroll.set)
        self._lock_tree_header_drag(self.bulk_tree)

    def _build_scan_tab(self) -> None:
        self.scan_tab.columnconfigure(0, weight=1)
        self.scan_tab.rowconfigure(2, weight=1)

        bar = ttk.Frame(self.scan_tab, padding=(0, 8, 0, 8))
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            bar,
            text=f"최근 스캔 파일 최대 {MAX_SCAN_PREVIEW_ROWS:,}개만 표시합니다. 전체 목록은 메모리에 보관되고 정리 계획/CSV에 반영됩니다.",
        ).grid(row=0, column=0, sticky="w")

        filters = ttk.Frame(self.scan_tab, padding=(0, 0, 0, 8))
        filters.grid(row=1, column=0, sticky="ew")
        filters.columnconfigure(8, weight=1)
        ttk.Label(filters, text="상태").grid(row=0, column=0, padx=(0, 6))
        status_combo = ttk.Combobox(
            filters,
            textvariable=self.scan_filter_status_var,
            values=("all", "정상", "검토 필요", "강한 불일치", "메타데이터 없음", "자동 수정 금지"),
            state="readonly",
            width=14,
        )
        status_combo.grid(row=0, column=1, padx=(0, 8))
        ttk.Label(filters, text="확장자").grid(row=0, column=2, padx=(0, 6))
        ext_combo = ttk.Combobox(
            filters,
            textvariable=self.scan_filter_extension_var,
            values=("all", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw", ".dng"),
            state="readonly",
            width=10,
        )
        ext_combo.grid(row=0, column=3, padx=(0, 8))
        ttk.Checkbutton(
            filters,
            text="중복 후보 폴더만",
            variable=self.scan_filter_duplicate_candidate_only_var,
        ).grid(row=0, column=4, padx=(0, 8))
        ttk.Checkbutton(
            filters,
            text="제외 폴더 내부만",
            variable=self.scan_filter_excluded_only_var,
        ).grid(row=0, column=5, padx=(0, 8))
        ttk.Button(filters, text="필터 적용", command=self._apply_scan_filters).grid(row=0, column=6, padx=(0, 8))
        ttk.Button(filters, text="필터 초기화", command=self._reset_scan_filters).grid(row=0, column=7)

        self.scan_tree = ttk.Treeview(self.scan_tab, columns=("path", "date", "source", "size"), show="headings")
        for column, label, width in (
            ("path", "파일", 700),
            ("date", "기준 날짜", 150),
            ("source", "날짜 기준", 90),
            ("size", "크기", 100),
        ):
            self.scan_tree.heading(column, text=label)
            self.scan_tree.column(column, width=width, anchor=tk.W)
        self.scan_tree.grid(row=2, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(self.scan_tab, orient=tk.VERTICAL, command=self.scan_tree.yview)
        scroll.grid(row=2, column=1, sticky="ns")
        self.scan_tree.configure(yscrollcommand=scroll.set)
        self._lock_tree_header_drag(self.scan_tree)

    def _build_duplicates_tab(self) -> None:
        self.duplicates_tab.columnconfigure(0, weight=1)
        self.duplicates_tab.columnconfigure(1, weight=2)
        self.duplicates_tab.columnconfigure(2, weight=2)
        self.duplicates_tab.rowconfigure(1, weight=1)

        controls = ttk.Frame(self.duplicates_tab, padding=(0, 8, 0, 8))
        controls.grid(row=0, column=0, columnspan=3, sticky="ew")
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="분석 범위").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.duplicate_scope_var,
            values=("selected_roots", "review_pairs"),
            state="readonly",
            width=14,
        ).grid(row=0, column=1, padx=(0, 8), sticky="w")
        self.duplicate_pair_combo = ttk.Combobox(
            controls,
            textvariable=self.duplicate_candidate_pair_var,
            values=("all",),
            state="readonly",
            width=32,
        )
        self.duplicate_pair_combo.grid(row=0, column=2, padx=(0, 8))
        ttk.Button(controls, text="후보 갱신", command=self._refresh_duplicate_pair_options).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(controls, text="중복 분석", command=self._start_duplicate_scan).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(controls, text="중복기반 메타계획", command=self._build_metadata_plan_from_filename_duplicates).grid(row=0, column=5, padx=(0, 8))
        ttk.Button(controls, text="중복 처리계획 저장", command=self._export_duplicate_resolution_plan).grid(row=0, column=6, padx=(0, 8))
        ttk.Button(controls, text="CSV 저장", command=self._export_clusters).grid(row=0, column=7)

        self.cluster_tree = ttk.Treeview(self.duplicates_tab, columns=("kind", "count", "score"), show="headings")
        for column, label, width in (("kind", "유형", 90), ("count", "파일 수", 80), ("score", "판정", 160)):
            self.cluster_tree.heading(column, text=label)
            self.cluster_tree.column(column, width=width, anchor=tk.W)
        self.cluster_tree.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        self.cluster_tree.bind("<<TreeviewSelect>>", self._show_cluster_files)
        self.cluster_tree.tag_configure("merge", foreground="#1f8f3a")
        self.cluster_tree.tag_configure("rename", foreground="#a55a00")
        cluster_scroll = ttk.Scrollbar(self.duplicates_tab, orient=tk.VERTICAL, command=self.cluster_tree.yview)
        cluster_scroll.grid(row=1, column=0, sticky="nse")
        self.cluster_tree.configure(yscrollcommand=cluster_scroll.set)

        self.cluster_files = ttk.Treeview(self.duplicates_tab, columns=("decision", "path", "date", "size"), show="headings")
        for column, label, width in (("decision", "처리", 90), ("path", "파일", 540), ("date", "기준 날짜", 150), ("size", "크기", 100)):
            self.cluster_files.heading(column, text=label)
            self.cluster_files.column(column, width=width, anchor=tk.W)
        self.cluster_files.grid(row=1, column=1, sticky="nsew")
        self.cluster_files.bind("<Double-1>", self._open_selected_cluster_file)
        self.cluster_files.bind("<<TreeviewSelect>>", self._show_preview_for_selected_file)
        files_scroll = ttk.Scrollbar(self.duplicates_tab, orient=tk.VERTICAL, command=self.cluster_files.yview)
        files_scroll.grid(row=1, column=1, sticky="nse")
        self.cluster_files.configure(yscrollcommand=files_scroll.set)
        self._lock_tree_header_drag(self.cluster_tree)
        self._lock_tree_header_drag(self.cluster_files)
        self._refresh_duplicate_pair_options()

        preview_frame = ttk.Frame(self.duplicates_tab)
        preview_frame.grid(row=1, column=2, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)
        ttk.Label(preview_frame, text="미리보기").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.preview_meta_var = tk.StringVar(value="파일을 선택하면 미리보기를 표시합니다.")
        ttk.Label(preview_frame, textvariable=self.preview_meta_var, wraplength=360, justify=tk.LEFT).grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.duplicate_insight_var = tk.StringVar(value="폴더쌍 인사이트가 여기에 표시됩니다.")
        ttk.Label(preview_frame, textvariable=self.duplicate_insight_var, wraplength=360, justify=tk.LEFT, foreground="#475467").grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.preview_label = ttk.Label(preview_frame, anchor=tk.CENTER)
        self.preview_label.grid(row=1, column=0, sticky="nsew")

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
        ttk.Button(controls, text="전략 비교", command=self._compare_plan_strategies).grid(row=0, column=6, padx=(8, 0))
        ttk.Checkbutton(controls, text="읽기 전용", variable=self.read_only_var).grid(row=0, column=7, padx=(8, 0))
        ttk.Button(controls, text="실행", command=self._execute_plan).grid(row=0, column=8, padx=(8, 0))
        ttk.Button(controls, text="계획 CSV", command=self._export_plan).grid(row=0, column=9, padx=(8, 0))

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

    def _reset_scan_flags(self) -> None:
        self.has_folder_inventory = False
        self.has_date_audit = False
        self.has_photo_records = False
        self.has_duplicate_scan = False

    def _workflow_state_text(self, step_id: str) -> str:
        done = self.workflow_completed.get(step_id, False)
        selected = self.workflow_selection.get(step_id, False)
        if done:
            return "재실행" if selected else "완료표시"
        return "실행" if selected else "미실행"

    def _render_workflow_tree(self) -> None:
        if not hasattr(self, "workflow_tree"):
            return
        self.workflow_tree.delete(*self.workflow_tree.get_children())
        for step_id, label in self.workflow_steps:
            state_text = self._workflow_state_text(step_id)
            tag = "done" if (self.workflow_completed.get(step_id, False) and not self.workflow_selection.get(step_id, False)) else "active"
            self.workflow_tree.insert("", tk.END, iid=step_id, values=(state_text, label), tags=(tag,))

    def _on_workflow_click(self, event) -> str | None:
        if self.workflow_tree.identify_region(event.x, event.y) == "heading":
            return "break"
        row_id = self.workflow_tree.identify_row(event.y)
        if not row_id:
            return None
        done = self.workflow_completed.get(row_id, False)
        selected = self.workflow_selection.get(row_id, False)
        if done:
            self.workflow_selection[row_id] = not selected
        else:
            self.workflow_selection[row_id] = not selected
        self._render_workflow_tree()
        return "break"

    def _mark_step_completed(self, step_id: str) -> None:
        self.workflow_completed[step_id] = True
        self.workflow_selection[step_id] = False
        self._render_workflow_tree()
        self.after(10, self._continue_workflow_queue)

    def _continue_workflow_queue(self) -> None:
        if not self.workflow_running:
            return
        if self.worker and self.worker.is_alive():
            return
        if not self.workflow_queue:
            self.workflow_running = False
            return
        step_id = self.workflow_queue.pop(0)
        if step_id == "step1":
            self._start_structure_overview()
        elif step_id == "step2":
            self._start_folder_detail()
        elif step_id == "step3":
            self._start_date_audit()
        elif step_id == "step4":
            self._start_photo_metadata()
        elif step_id == "step5":
            self._start_filename_duplicate_scan()
        elif step_id == "step6":
            saved = self._export_review_bundle()
            if saved:
                self._mark_step_completed("step6")
            else:
                self.workflow_running = False

    def _run_selected_workflow(self) -> None:
        if self.workflow_running:
            self.status_var.set("이미 선택 실행이 진행 중입니다.")
            return
        queue: list[str] = []
        for step_id, _label in self.workflow_steps:
            if self.workflow_selection.get(step_id, False):
                queue.append(step_id)
        if not queue:
            self.status_var.set("체크된 작업이 없습니다.")
            return
        self.workflow_queue = queue
        self.workflow_running = True
        self._continue_workflow_queue()

    def _start_structure_overview(self) -> None:
        source = self.source_var.get().strip()
        if not os.path.isdir(source):
            messagebox.showerror("원본 오류", "존재하는 폴더 또는 드라이브를 선택하세요.")
            return
        self.stop_event.clear()
        self.folders = []
        self.date_audit = []
        self.records = []
        self.duplicate_records = []
        self.plan = []
        self._reset_scan_flags()
        self._clear_trees()
        self.status_var.set("구조 개요(폴더 구조만)를 실행 중입니다.")
        self.worker = threading.Thread(target=self._structure_overview_worker, args=(source,), daemon=True)
        self.worker.start()

    def _structure_overview_worker(self, source: str) -> None:
        engine = PhotoLibraryEngine(lambda text: self.after(0, self.status_var.set, text), self.stop_event)
        folders = engine.scan_folder_structure(source)
        if self.stop_event.is_set():
            self.after(0, self.status_var.set, "구조 개요가 중지되었습니다.")
            return
        self.folders = folders
        self.has_folder_inventory = True
        self._reindex_folders()
        self.after(0, self._render_folders)
        self.after(0, self.summary_var.set, f"폴더 {len(folders):,}개")
        self.after(0, self.status_var.set, "구조 개요 완료. 다음은 2 폴더 상세 구조를 실행하세요.")
        self.after(0, self._mark_step_completed, "step1")

    def _start_folder_detail(self) -> None:
        source = self.source_var.get().strip()
        if not os.path.isdir(source):
            messagebox.showerror("원본 오류", "존재하는 폴더 또는 드라이브를 선택하세요.")
            return
        self.stop_event.clear()
        self.folders = []
        self.date_audit = []
        self.records = []
        self.duplicate_records = []
        self.plan = []
        self._reset_scan_flags()
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
        self.has_folder_inventory = True
        self.has_date_audit = True
        self._reindex_folders()
        self.after(0, self._render_folders)
        self.after(0, self._render_date_audit)
        self.after(0, self.status_var.set, "폴더 상세 구조 완료")
        self.after(0, self._mark_step_completed, "step2")
        self.after(0, self._mark_step_completed, "step3")

    def _start_photo_metadata(self) -> None:
        roots = self._selected_scan_roots()
        if not roots:
            messagebox.showinfo("대상 없음", "폴더 구조에서 정리 대상을 먼저 선택하세요.")
            return
        self.stop_event.clear()
        self.records = []
        self.duplicate_records = []
        self.has_photo_records = False
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
        self.has_photo_records = True
        self.after(0, self._render_scan_tree, records)
        self.after(0, self.status_var.set, f"사진 메타데이터 완료: {len(records):,}개")
        self.after(0, self._mark_step_completed, "step4")

    def _start_filename_duplicate_scan(self) -> None:
        roots = self._selected_scan_roots()
        if not roots:
            messagebox.showinfo("대상 없음", "폴더 구조에서 정리 대상을 먼저 선택하세요.")
            return
        self.stop_event.clear()
        self.clusters = []
        self.has_duplicate_scan = False
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
        pair_stats: dict[tuple[str, str], int] = {}
        for name_key, files in groups.items():
            if len(files) <= 1:
                continue
            size_groups: dict[int, list[PhotoRecord]] = {}
            for record in files:
                size_groups.setdefault(record.size, []).append(record)

            exact_clusters: list[list[PhotoRecord]] = []
            distinct_fingerprints: set[str] = set()
            for size_records in size_groups.values():
                if len(size_records) == 1:
                    record = size_records[0]
                    fingerprint = f"{record.size}:{record.modified_at}"
                    distinct_fingerprints.add(fingerprint)
                    continue
                by_digest: dict[str, list[PhotoRecord]] = {}
                for record in size_records:
                    digest = self._quick_file_digest(record.path)
                    fingerprint = digest or f"{record.size}:{record.modified_at}"
                    distinct_fingerprints.add(fingerprint)
                    by_digest.setdefault(fingerprint, []).append(record)
                for dup_records in by_digest.values():
                    if len(dup_records) > 1:
                        exact_clusters.append(sorted(dup_records, key=lambda item: item.path.lower()))

            if exact_clusters:
                flat_exact = sorted(
                    [record for chunk in exact_clusters for record in chunk],
                    key=lambda item: item.path.lower(),
                )
                self.clusters.append(
                    PhotoCluster(
                        "통합",
                        f"name:{name_key} | 동일파일 {len(flat_exact):,}개",
                        tuple(flat_exact),
                    )
                )
                self._accumulate_folder_pair_stats(flat_exact, pair_stats)

            if len(distinct_fingerprints) > 1:
                self.clusters.append(
                    PhotoCluster(
                        "이름정리",
                        f"name:{name_key} | 서로 다른 내용 {len(distinct_fingerprints):,}종류",
                        tuple(sorted(files, key=lambda item: item.path.lower())),
                    )
                )
        self.clusters.sort(key=lambda item: (item.kind != "통합", -len(item.files), item.score))
        self.cluster_tree.delete(*self.cluster_tree.get_children())
        self.cluster_files.delete(*self.cluster_files.get_children())
        for index, cluster in enumerate(self.clusters):
            tag = "merge" if cluster.kind == "통합" else ("rename" if cluster.kind == "이름정리" else "")
            self.cluster_tree.insert("", tk.END, iid=str(index), values=(cluster.kind, len(cluster.files), cluster.score), tags=(tag,))
        self._render_duplicate_pair_insight(pair_stats)
        self.has_duplicate_scan = True
        self.status_var.set(f"파일명 중복 검사 완료: 그룹 {len(self.clusters):,}개")
        self._mark_step_completed("step5")

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
        self._reset_scan_flags()
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
        self.has_folder_inventory = True
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
        self.has_folder_inventory = True
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
        self.has_date_audit = False
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
        self.has_date_audit = True
        self.after(0, self._render_date_audit)
        warning_count = sum(1 for record in records if record.status != "정상")
        self.after(0, self.summary_var.set, f"날짜 검토 {len(records):,}개, 주의 항목 {warning_count:,}개")
        self.after(0, self.status_var.set, "3단계 완료. 자동 수정 금지/강한 불일치/검토 필요 항목을 우선 확인하세요.")
        self.after(0, self._mark_step_completed, "step3")

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
        rows = sorted(
            self.date_audit,
            key=lambda item: (DATE_STATUS_PRIORITY.get(item.status, 99), item.path.lower()),
        )
        for record in rows[:MAX_PLAN_PREVIEW_ROWS]:
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
        self._render_bulk_suggestions()

    def _render_bulk_suggestions(self) -> None:
        self.bulk_tree.delete(*self.bulk_tree.get_children())
        for index, item in enumerate(self.bulk_suggestions):
            apply_mark = "☑" if item.get("enabled") else "☐"
            self.bulk_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(apply_mark, item.get("kind", ""), item.get("current", ""), item.get("proposed", ""), item.get("path", "")),
            )

    def _on_bulk_tree_click(self, event) -> None:
        row_id = self.bulk_tree.identify_row(event.y)
        if not row_id:
            return
        column = self.bulk_tree.identify_column(event.x)
        if column != "#1":
            return
        idx = int(row_id)
        if idx < 0 or idx >= len(self.bulk_suggestions):
            return
        suggestion = self.bulk_suggestions[idx]
        if suggestion.get("kind") == "메타검토":
            self.status_var.set("메타 검토 항목은 자동 적용이 아니라 계획 저장 전용입니다.")
            return
        suggestion["enabled"] = not bool(suggestion.get("enabled"))
        self._render_bulk_suggestions()

    def _generate_bulk_suggestions(self) -> None:
        suggestions: list[dict[str, object]] = []
        for record in self.date_audit:
            if record.status not in {"검토 필요", "강한 불일치", "자동 수정 금지", "메타데이터 없음"}:
                continue
            path = record.path
            preferred_date = record.filename_date or record.folder_date or record.filesystem_date
            if preferred_date and preferred_date != record.filesystem_date:
                suggestions.append(
                    {
                        "kind": "날짜보정",
                        "path": path,
                        "current": record.filesystem_date,
                        "proposed": preferred_date,
                        "enabled": record.status != "자동 수정 금지",
                    }
                )
            if record.metadata_date in {"", "미확인"}:
                suggestions.append(
                    {
                        "kind": "메타검토",
                        "path": path,
                        "current": record.metadata_date or "없음",
                        "proposed": "수동 확인 필요",
                        "enabled": False,
                    }
                )
            filename_token = record.filename_date.replace("-", "") if record.filename_date else ""
            if filename_token:
                current_name = Path(path).name
                ext = Path(path).suffix
                proposed_name = f"{filename_token}_{current_name}" if not current_name.startswith(filename_token) else current_name
                if proposed_name != current_name:
                    safe_proposed = sanitize_filename_suggestion(
                        proposed_name if proposed_name.endswith(ext) else proposed_name + ext,
                        current_name,
                    )
                    suggestions.append(
                        {
                            "kind": "파일명제안",
                            "path": path,
                            "current": current_name,
                            "proposed": safe_proposed,
                            "enabled": record.status != "자동 수정 금지",
                        }
                    )
        self.bulk_suggestions = suggestions
        self._render_bulk_suggestions()
        enabled = sum(1 for item in suggestions if item.get("enabled"))
        self.status_var.set(f"일괄 제안 생성: 전체 {len(suggestions):,}건, 자동 반영 가능 {enabled:,}건")

    def _apply_bulk_suggestions(self) -> None:
        if not self.bulk_suggestions:
            messagebox.showinfo("제안 없음", "먼저 일괄 제안 생성 버튼을 누르세요.")
            return
        applied_dates = 0
        applied_names = 0
        metadata_notes = 0
        for item in self.bulk_suggestions:
            if not item.get("enabled"):
                if item.get("kind") == "메타검토":
                    metadata_notes += 1
                continue
            path = str(item.get("path", "")).strip()
            if not path:
                continue
            kind = str(item.get("kind", ""))
            if kind == "날짜보정":
                parsed = parse_review_date(item.get("proposed"))
                if parsed:
                    self.review_date_overrides[path.lower()] = parsed
                    applied_dates += 1
            elif kind == "파일명제안":
                proposed = str(item.get("proposed", "")).strip()
                if proposed:
                    current_name = Path(path).name
                    self.review_rename_suggestions[path.lower()] = sanitize_filename_suggestion(proposed, current_name)
                    applied_names += 1
            elif kind == "메타검토":
                metadata_notes += 1
        if metadata_notes:
            self.review_metadata_suggestions = [
                {"path": item.get("path", ""), "action": "manual_metadata_review", "proposed": item.get("proposed", "수동 확인 필요")}
                for item in self.bulk_suggestions
                if item.get("kind") == "메타검토"
            ]
        self.status_var.set(
            f"일괄 제안 반영: 날짜 {applied_dates:,}건, 파일명 {applied_names:,}건, 메타 수동검토 {metadata_notes:,}건"
        )

    def _export_metadata_edit_plan(self) -> None:
        if not self.review_metadata_suggestions:
            messagebox.showinfo("메타 계획 없음", "메타 검토 제안을 먼저 생성/반영하세요.")
            return
        review_root = self._review_root()
        review_root.mkdir(parents=True, exist_ok=True)
        json_path = review_root / "metadata_edit_plan.json"
        csv_path = review_root / "metadata_edit_plan.csv"
        payload = {
            "mode": "plan_only",
            "write_enabled": False,
            "requires_manual_verification": True,
            "items": self.review_metadata_suggestions,
        }
        with open(json_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["path", "action", "proposed", "status"])
            for item in self.review_metadata_suggestions:
                writer.writerow([item.get("path", ""), item.get("action", ""), item.get("proposed", ""), "manual_review_required"])
        self.status_var.set(f"메타데이터 계획 저장 완료(쓰기 금지): {json_path}")

    def _start_scan(self) -> None:
        roots = self._selected_scan_roots()
        if not roots:
            messagebox.showerror("정리 대상 필요", "폴더 구조에서 정리 대상을 최소 1개 체크하세요.")
            return
        self.stop_event.clear()
        self.records = []
        self.duplicate_records = []
        self.clusters = []
        self.plan = []
        self.has_photo_records = False
        self.has_duplicate_scan = False
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
        self.has_photo_records = True
        self.after(0, self._render_scan_tree, records)
        self.after(0, self._finish_structure_scan)
        self.after(0, self._mark_step_completed, "step4")

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

    def _duplicate_candidate_paths(self) -> set[str]:
        targets: set[str] = set()
        for item in self.review_duplicate_candidates:
            left = str(item.get("left", "")).strip()
            right = str(item.get("right", "")).strip()
            if left:
                targets.add(left.lower())
            if right:
                targets.add(right.lower())
        return targets

    def _record_matches_filters(
        self,
        record: PhotoRecord,
        status_map: dict[str, str],
        candidate_paths: set[str],
    ) -> bool:
        status_filter = self.scan_filter_status_var.get()
        ext_filter = self.scan_filter_extension_var.get().lower()
        dup_only = self.scan_filter_duplicate_candidate_only_var.get()
        excluded_only = self.scan_filter_excluded_only_var.get()

        if status_filter != "all":
            if status_map.get(record.path, "정상") != status_filter:
                return False
        if ext_filter != "all":
            if Path(record.path).suffix.lower() != ext_filter:
                return False
        if dup_only:
            parent_lower = str(Path(record.path).parent).lower()
            if not any(parent_lower.startswith(target + os.sep) or parent_lower == target for target in candidate_paths):
                return False
        if excluded_only:
            parent_path = str(Path(record.path).parent)
            folder_record = self.folder_map.get(parent_path)
            if not folder_record:
                if not is_excluded_folder(parent_path):
                    return False
            else:
                if folder_record.include and not is_excluded_folder(parent_path):
                    return False
        return True

    def _render_scan_tree(self, records: list[PhotoRecord]) -> None:
        self.scan_tree.delete(*self.scan_tree.get_children())
        shown = 0
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
            shown += 1
            if shown >= MAX_SCAN_PREVIEW_ROWS:
                break
        suffix = " (표시는 일부)" if len(records) > MAX_SCAN_PREVIEW_ROWS else ""
        self.summary_var.set(f"필터 결과 {len(records):,}개{suffix}")

    def _apply_scan_filters(self) -> None:
        if not self.records:
            messagebox.showinfo("스캔 필요", "먼저 사진 스캔을 실행하세요.")
            return
        status_map = {row.path: row.status for row in self.date_audit}
        candidate_paths = self._duplicate_candidate_paths()
        filtered = [
            record
            for record in self.records
            if self._record_matches_filters(record, status_map, candidate_paths)
        ]
        self._render_scan_tree(filtered)
        self.status_var.set(f"사진 목록 필터 적용: {len(filtered):,}/{len(self.records):,}개")

    def _reset_scan_filters(self) -> None:
        self.scan_filter_status_var.set("all")
        self.scan_filter_extension_var.set("all")
        self.scan_filter_duplicate_candidate_only_var.set(False)
        self.scan_filter_excluded_only_var.set(False)
        if self.records:
            self._render_scan_tree(self.records)
        self.status_var.set("사진 목록 필터 초기화 완료")

    def _refresh_duplicate_pair_options(self) -> None:
        options = ["all"]
        for item in self.review_duplicate_candidates:
            left = str(item.get("left", "")).strip()
            right = str(item.get("right", "")).strip()
            if not left and not right:
                continue
            options.append(f"{left} <-> {right}")
        self.duplicate_pair_combo.configure(values=options)
        if self.duplicate_candidate_pair_var.get() not in options:
            self.duplicate_candidate_pair_var.set("all")

    def _records_for_duplicate_scope(self) -> list[PhotoRecord]:
        if self.duplicate_scope_var.get() != "review_pairs":
            return self.records
        if not self.review_duplicate_candidates:
            self.status_var.set("review_pairs 범위에 후보가 없습니다. Review 로드 후 duplicate_candidates를 확인하세요.")
            return []
        selected_pair = self.duplicate_candidate_pair_var.get()
        scoped_pairs = self.review_duplicate_candidates
        if selected_pair != "all":
            scoped_pairs = []
            for item in self.review_duplicate_candidates:
                left = str(item.get("left", "")).strip()
                right = str(item.get("right", "")).strip()
                if f"{left} <-> {right}" == selected_pair:
                    scoped_pairs.append(item)
            if not scoped_pairs:
                self.status_var.set("선택한 후보쌍이 유효하지 않습니다. 후보 갱신 후 다시 선택하세요.")
                return []
        targets: list[str] = []
        for item in scoped_pairs:
            left = str(item.get("left", "")).strip()
            right = str(item.get("right", "")).strip()
            if left:
                targets.append(left.lower())
            if right:
                targets.append(right.lower())
        if not targets:
            return []
        scoped: list[PhotoRecord] = []
        for record in self.records:
            parent_lower = str(Path(record.path).parent).lower()
            if any(parent_lower.startswith(target + os.sep) or parent_lower == target for target in targets):
                scoped.append(record)
        if not scoped:
            self.status_var.set("review_pairs 범위에서 일치하는 사진이 없습니다. 후보 경로와 선택 루트를 확인하세요.")
        return scoped

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
        scoped_records = self._records_for_duplicate_scope()
        if not scoped_records:
            messagebox.showinfo("대상 없음", "중복 분석 대상이 없습니다. 범위를 확인하세요.")
            return
        self.stop_event.clear()
        self.clusters = []
        self.duplicate_records = []
        self.has_duplicate_scan = False
        self.cluster_tree.delete(*self.cluster_tree.get_children())
        self.cluster_files.delete(*self.cluster_files.get_children())
        scope_label = "선택 폴더"
        if self.duplicate_scope_var.get() == "review_pairs":
            scope_label = f"검수 후보쌍({self.duplicate_candidate_pair_var.get()})"
        self.status_var.set(f"중복/유사 분석 시작: {scope_label}, 대상 {len(scoped_records):,}개")
        self.worker = threading.Thread(target=self._duplicate_scan_worker, args=(scoped_records,), daemon=True)
        self.worker.start()

    def _duplicate_scan_worker(self, scoped_records: list[PhotoRecord]) -> None:
        engine = PhotoLibraryEngine(lambda text: self.after(0, self.status_var.set, text), self.stop_event)
        records = engine.add_fingerprints(scoped_records)
        if self.stop_event.is_set():
            self.after(0, self.status_var.set, "중복/유사 분석이 중지되었습니다.")
            return
        self.after(0, self._refresh_clusters_for_records, records)

    def _refresh_clusters_for_records(self, records: list[PhotoRecord]) -> None:
        if not records:
            self.duplicate_records = []
            self.clusters = []
            self.has_duplicate_scan = True
            return
        self.duplicate_records = records
        engine = PhotoLibraryEngine(lambda text: self.status_var.set(text), self.stop_event)
        self.clusters = engine.duplicate_clusters(records, int(self.threshold_var.get()))
        self.has_duplicate_scan = True
        self.cluster_tree.delete(*self.cluster_tree.get_children())
        self.cluster_files.delete(*self.cluster_files.get_children())
        for index, cluster in enumerate(self.clusters):
            self.cluster_tree.insert("", tk.END, iid=str(index), values=(cluster.kind, len(cluster.files), cluster.score))
        self.summary_var.set(f"분석 대상 {len(records):,}개, 중복/유사 그룹 {len(self.clusters):,}개")
        self.status_var.set("중복/유사 분석 완료")
        self._mark_step_completed("step5")

    def _stop(self) -> None:
        self.stop_event.set()
        self.workflow_running = False
        self.workflow_queue = []
        self.status_var.set("중지 요청을 보냈습니다.")

    def _refresh_clusters(self) -> None:
        if not self.duplicate_records:
            return
        engine = PhotoLibraryEngine(lambda text: self.status_var.set(text), self.stop_event)
        self.clusters = engine.duplicate_clusters(self.duplicate_records, int(self.threshold_var.get()))
        self.has_duplicate_scan = True
        self.cluster_tree.delete(*self.cluster_tree.get_children())
        self.cluster_files.delete(*self.cluster_files.get_children())
        for index, cluster in enumerate(self.clusters):
            self.cluster_tree.insert("", tk.END, iid=str(index), values=(cluster.kind, len(cluster.files), cluster.score))
        self.summary_var.set(f"분석 대상 {len(self.duplicate_records):,}개, 중복/유사 그룹 {len(self.clusters):,}개")
        self.status_var.set("분석 완료")

    def _show_cluster_files(self, _event=None) -> None:
        self.cluster_files.delete(*self.cluster_files.get_children())
        selection = self.cluster_tree.selection()
        if not selection:
            return
        cluster = self.clusters[int(selection[0])]
        for idx, record in enumerate(cluster.files):
            if cluster.kind == "통합":
                decision = "유지" if idx == 0 else "통합"
            elif cluster.kind == "이름정리":
                decision = "이름변경"
            else:
                decision = ""
            self.cluster_files.insert(
                "",
                tk.END,
                values=(decision, record.path, record.best_date.strftime("%Y-%m-%d %H:%M"), format_bytes(record.size)),
            )
        children = self.cluster_files.get_children()
        if children:
            self.cluster_files.selection_set(children[0])
            self.cluster_files.focus(children[0])
            self._show_preview_for_selected_file()

    def _quick_file_digest(self, path: str) -> str:
        try:
            with open(path, "rb") as file:
                data = file.read(1024 * 128)
        except OSError:
            return ""
        return hashlib.sha1(data).hexdigest() if data else ""

    def _accumulate_folder_pair_stats(self, records: list[PhotoRecord], pair_stats: dict[tuple[str, str], int]) -> None:
        folders = sorted({str(Path(record.path).parent) for record in records})
        for i in range(len(folders)):
            for j in range(i + 1, len(folders)):
                pair_stats[(folders[i], folders[j])] = pair_stats.get((folders[i], folders[j]), 0) + 1

    def _render_duplicate_pair_insight(self, pair_stats: dict[tuple[str, str], int]) -> None:
        if not hasattr(self, "duplicate_insight_var"):
            return
        if not pair_stats:
            self.duplicate_insight_var.set("폴더쌍 인사이트 없음: 동일 파일이 여러 폴더로 반복된 패턴이 발견되지 않았습니다.")
            return
        top = sorted(pair_stats.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))[:3]
        lines = ["중복 버스트 상위 폴더쌍:"]
        for (left, right), count in top:
            lines.append(f"- {Path(left).name} <-> {Path(right).name}: {count:,}개 그룹")
        self.duplicate_insight_var.set("\n".join(lines))

    def _show_preview_for_selected_file(self, _event=None) -> None:
        selection = self.cluster_files.selection()
        if not selection:
            self.preview_label.configure(image="")
            self.preview_meta_var.set("파일을 선택하면 미리보기를 표시합니다.")
            self.preview_image_ref = None
            return
        values = self.cluster_files.item(selection[0], "values")
        if not values:
            return
        path = str(values[1])
        if not os.path.isfile(path):
            self.preview_label.configure(image="")
            self.preview_meta_var.set(f"파일이 없어 미리보기를 표시할 수 없습니다.\n{path}")
            self.preview_image_ref = None
            return
        if Image is None:
            self.preview_label.configure(image="")
            self.preview_meta_var.set(f"Pillow 미지원 환경입니다.\n{path}")
            self.preview_image_ref = None
            return
        try:
            image = Image.open(path)
            image.thumbnail((420, 320))
            tk_image = ImageTk.PhotoImage(image)
        except Exception as exc:
            self.preview_label.configure(image="")
            self.preview_meta_var.set(f"미리보기 실패: {exc}\n{path}")
            self.preview_image_ref = None
            return
        self.preview_label.configure(image=tk_image)
        self.preview_image_ref = tk_image
        stat = os.stat(path)
        self.preview_meta_var.set(
            f"{Path(path).name}\n{format_bytes(stat.st_size)} | 수정 {datetime.fromtimestamp(stat.st_mtime):%Y-%m-%d %H:%M}\n{path}"
        )

    def _build_metadata_plan_from_filename_duplicates(self) -> None:
        if not self.clusters:
            messagebox.showinfo("중복 결과 필요", "먼저 중복검사를 실행하세요.")
            return
        plans: list[dict[str, object]] = []
        for cluster in self.clusters:
            if cluster.kind not in {"통합", "이름정리", "파일명중복"}:
                continue
            candidate_dates: list[datetime] = []
            for record in cluster.files:
                parsed = parse_filename_date(record.path)
                if parsed:
                    candidate_dates.append(parsed)
            if not candidate_dates:
                candidate_dates = [record.best_date for record in cluster.files]
            canonical = min(candidate_dates) if candidate_dates else None
            for record in cluster.files:
                plans.append(
                    {
                        "path": record.path,
                        "action": "manual_metadata_review",
                        "proposed": canonical.strftime("%Y-%m-%d") if canonical else "",
                        "reason": "filename_duplicate_group",
                        "group_score": cluster.score,
                    }
                )
        if not plans:
            messagebox.showinfo("대상 없음", "파일명 중복 그룹에서 메타 계획 대상을 만들지 못했습니다.")
            return
        existing = {str(item.get("path", "")).lower(): item for item in self.review_metadata_suggestions}
        for item in plans:
            existing[str(item.get("path", "")).lower()] = item
        self.review_metadata_suggestions = list(existing.values())
        self.status_var.set(f"파일명 중복 기반 메타 계획 반영: {len(plans):,}건 (누적 {len(self.review_metadata_suggestions):,}건)")

    def _records_for_plan(self) -> list[PhotoRecord]:
        if not self.records:
            return []
        if not self.review_date_overrides:
            return self.records
        updated: list[PhotoRecord] = []
        for record in self.records:
            key = record.path.lower()
            override_date = self.review_date_overrides.get(key)
            if not override_date:
                updated.append(record)
                continue
            updated.append(
                PhotoRecord(
                    path=record.path,
                    size=record.size,
                    created_at=record.created_at,
                    modified_at=record.modified_at,
                    best_date=override_date or record.best_date,
                    date_source="검수지정일" if override_date else record.date_source,
                    place=record.place,
                    sha256=record.sha256,
                    phash=record.phash,
                )
            )
        return updated

    def _apply_review_plan_overrides(self, actions: list[OrganizeAction]) -> list[OrganizeAction]:
        if not actions:
            return []
        updated: list[OrganizeAction] = []
        for action in actions:
            source_path = Path(action.source)
            destination_path = Path(action.destination)
            key = action.source.lower()
            reason = action.reason

            new_name = self.review_rename_suggestions.get(key)
            if new_name:
                ext = source_path.suffix
                normalized_name = sanitize_filename_suggestion(new_name, source_path.name)
                if ext and not normalized_name.lower().endswith(ext.lower()):
                    normalized_name = Path(normalized_name).stem + ext
                destination_path = destination_path.with_name(safe_name(normalized_name))
                reason = f"{reason}+검수파일명"

            parent_key = str(source_path.parent).lower()
            new_folder = self.review_folder_rename_suggestions.get(parent_key)
            if new_folder:
                safe_folder = safe_name(new_folder)
                parts = list(destination_path.parts)
                if len(parts) >= 2:
                    parts[-2] = safe_folder
                    destination_path = Path(*parts)
                    reason = f"{reason}+검수폴더명"

            updated.append(OrganizeAction(action.source, str(destination_path), reason))
        return self._resolve_plan_destination_conflicts(updated)

    def _resolve_plan_destination_conflicts(self, actions: list[OrganizeAction]) -> list[OrganizeAction]:
        seen: dict[str, int] = {}
        resolved: list[OrganizeAction] = []
        for action in actions:
            destination = Path(action.destination)
            key = str(destination).lower()
            if key not in seen:
                seen[key] = 0
                resolved.append(action)
                continue
            seen[key] += 1
            index = seen[key]
            stem = destination.stem
            suffix = destination.suffix
            candidate = destination.with_name(f"{stem}_{index}{suffix}")
            while str(candidate).lower() in seen:
                index += 1
                candidate = destination.with_name(f"{stem}_{index}{suffix}")
            seen[str(candidate).lower()] = 0
            resolved.append(OrganizeAction(action.source, str(candidate), f"{action.reason}+충돌해소"))
        return resolved

    def _build_plan(self) -> None:
        destination = self.destination_var.get().strip()
        if not self.records:
            messagebox.showinfo("스캔 필요", "먼저 4 사진스캔을 실행하세요.")
            return
        if not destination:
            messagebox.showwarning("대상 폴더 필요", "정리 대상 폴더를 선택하세요.")
            return
        engine = PhotoLibraryEngine(lambda text: self.status_var.set(text), self.stop_event)
        plan_records = self._records_for_plan()
        self.plan = engine.build_organize_plan(plan_records, destination, self.mode_var.get(), self.plan_scheme_var.get())
        self.plan = self._apply_review_plan_overrides(self.plan)
        self._render_plan_tree()
        extra = len(self.plan) - min(len(self.plan), MAX_PLAN_PREVIEW_ROWS)
        suffix = f" 표에는 처음 {MAX_PLAN_PREVIEW_ROWS:,}건만 표시됩니다." if extra > 0 else ""
        self._save_plan_files()
        review_hint = ""
        if self.review_date_overrides or self.review_rename_suggestions or self.review_folder_rename_suggestions:
            review_hint = (
                f" (검수 반영: 날짜 {len(self.review_date_overrides):,}, "
                f"파일명 {len(self.review_rename_suggestions):,}, 폴더명 {len(self.review_folder_rename_suggestions):,})"
            )
        self.status_var.set(f"정리 계획 {len(self.plan):,}건 생성{review_hint}. 읽기 전용이면 실행은 막힙니다.{suffix}")

    def _plan_metrics(self, actions: list[OrganizeAction]) -> dict[str, int]:
        collisions = 0
        existing_conflicts = 0
        seen: dict[str, str] = {}
        folders: set[str] = set()
        total_bytes = 0
        for action in actions:
            destination_path = Path(action.destination)
            key = action.destination.lower()
            folders.add(str(destination_path.parent).lower())
            if key in seen and seen[key] != action.source.lower():
                collisions += 1
            seen[key] = action.source.lower()
            if destination_path.exists():
                try:
                    same = os.path.samefile(action.source, action.destination)
                except OSError:
                    same = False
                if not same:
                    existing_conflicts += 1
            try:
                total_bytes += os.path.getsize(action.source)
            except OSError:
                pass
        return {
            "files": len(actions),
            "bytes": total_bytes,
            "collisions": collisions,
            "existing_conflicts": existing_conflicts,
            "folders": len(folders),
        }

    def _compare_plan_strategies(self) -> None:
        if not self.records:
            messagebox.showinfo("스캔 필요", "먼저 4 사진스캔을 실행하세요.")
            return
        destination = self.destination_var.get().strip()
        if not destination:
            messagebox.showwarning("대상 폴더 필요", "정리 대상 폴더를 선택하세요.")
            return

        engine = PhotoLibraryEngine(lambda text: self.status_var.set(text), self.stop_event)
        plan_records = self._records_for_plan()
        strategy_pairs = [
            ("year_month_place", "year_month_event"),
            ("year_month_place", "year_month_day"),
            ("year_month", "year_month_event"),
            ("year_month", "year_source_month"),
            ("date_place", "year_month_day"),
            ("date_place", "year_month_event"),
        ]
        results: list[dict[str, object]] = []
        for mode, scheme in strategy_pairs:
            actions = engine.build_organize_plan(plan_records, destination, mode, scheme)
            actions = self._apply_review_plan_overrides(actions)
            metric = self._plan_metrics(actions)
            results.append(
                {
                    "mode": mode,
                    "scheme": scheme,
                    "files": metric["files"],
                    "bytes": metric["bytes"],
                    "collisions": metric["collisions"],
                    "existing_conflicts": metric["existing_conflicts"],
                    "folders": metric["folders"],
                }
            )
        results.sort(key=lambda item: (item["existing_conflicts"], item["collisions"], int(item["folders"])))
        self._render_plan_review(destination, strategy_results=results)
        self.status_var.set(f"전략 비교 완료: {len(results):,}개 전략")

    def _execute_plan(self) -> None:
        if self.read_only_var.get():
            messagebox.showwarning("읽기 전용", "읽기 전용 모드에서는 파일을 이동하지 않습니다.")
            return
        if not self.plan:
            messagebox.showinfo("계획 없음", "먼저 정리 계획을 생성하세요.")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("작업 진행 중", "현재 작업이 끝난 뒤 다시 실행하세요.")
            return
        source = self.source_var.get().strip()
        destination = self.destination_var.get().strip()
        if not source or not os.path.isdir(source):
            messagebox.showerror("원본 오류", "서비스 인벤토리를 만들 수 있는 원본 폴더를 선택하세요.")
            return
        if not destination:
            messagebox.showwarning("대상 폴더 필요", "정리 대상 폴더를 선택하세요.")
            return
        if not messagebox.askyesno(
            "서비스 계획 검사",
            "현재 계획과 서비스가 생성한 보관 계획이 정확히 같은지 검사합니다. 계속할까요?",
        ):
            return

        plan_snapshot = tuple(self.plan)
        event_threshold = self.threshold_var.get()
        service_db = str(Path(destination) / REVIEW_DIR_NAME / "root_gui_service.sqlite")
        self.status_var.set("서비스 인벤토리 및 승인 게이트를 준비하는 중...")
        self.worker = threading.Thread(
            target=self._service_execute_worker,
            args=(plan_snapshot, source, destination, event_threshold, service_db),
            daemon=True,
        )
        self.worker.start()

    @staticmethod
    def _normalized_plan_pairs(actions) -> Counter[tuple[str, str]]:
        def normalize(path: str) -> str:
            return os.path.normcase(os.path.abspath(os.path.normpath(path)))

        return Counter((normalize(action.source), normalize(action.destination)) for action in actions)

    @staticmethod
    def _service_data(result: dict, command: str) -> dict:
        if not result.get("ok"):
            errors = "; ".join(str(item) for item in result.get("errors", []))
            warnings = "; ".join(str(item) for item in result.get("warnings", []))
            next_safe_action = str(result.get("next_safe_action", "")).strip()
            detail = f"{command} 실패: {errors or '알 수 없는 서비스 오류'}"
            if warnings:
                detail += f"\n경고: {warnings}"
            if next_safe_action:
                detail += f"\n다음 안전 조치: {next_safe_action}"
            raise RuntimeError(detail)
        return result.get("data", {})

    @staticmethod
    def _service_progress_message(payload: dict) -> str:
        operation = str(payload.get("operation", "service"))
        phase = str(payload.get("phase", "progress"))
        label = {
            "analysis": "분석",
            "sample_dry_run": "사전 점검",
            "dry_run_plan": "사전 점검",
            "hash_missing": "해시",
            "execute_plan": "서비스 실행",
            "resume_batch": "재개 실행",
            "rollback_batch": "롤백",
            "reconcile_batch": "재조정",
            "resume_batch_reconcile": "재개 정리",
        }.get(operation, operation)
        total = int(payload.get("total", 0) or 0)
        completed = int(payload.get("completed", payload.get("updated", payload.get("processed", 0))) or 0)
        failed = int(payload.get("failed", 0) or 0)
        if operation in {"analysis", "sample_dry_run"}:
            stage_label = {
                "starting": f"{label} 시작",
                "scanned": f"{label} 스캔 완료",
                "hashed": f"{label} 해시 완료",
                "planned": f"{label} 계획 작성",
                "budget_checked": f"{label} 용량 검토",
                "manifest_written": f"{label} 후보 명세 작성",
                "report_written": f"{label} 보고서 작성",
                "review_package_written": f"{label} 검토 패키지 작성",
                "completed": f"{label} 완료",
                "failed": f"{label} 실패",
            }.get(phase, f"{label} 진행 중")
            if phase == "starting":
                return stage_label
            if phase == "scanned":
                scanned = int(payload.get("scanned", completed) or 0)
                return f"{stage_label}: {scanned:,}개 파일"
            if phase == "hashed":
                hashed = int(payload.get("hashed", completed) or 0)
                return f"{stage_label}: {hashed:,}개 파일"
            if phase == "planned":
                archive_plans = int(payload.get("archive_plans", 0) or 0)
                raw_plans = int(payload.get("raw_to_jpg_plans", 0) or 0)
                return f"{stage_label}: 보관 {archive_plans:,}건, RAW 변환 {raw_plans:,}건"
            if phase == "budget_checked":
                can_run_batch = bool(payload.get("can_run_batch", False))
                required = int(payload.get("required_extra_bytes", 0) or 0)
                return f"{stage_label}: 실행 가능 {can_run_batch}, 추가 필요 {required:,}바이트"
            if phase == "manifest_written":
                candidate_count = int(payload.get("candidate_count", 0) or 0)
                return f"{stage_label}: {candidate_count:,}건"
            if phase == "report_written":
                return stage_label
            if phase == "review_package_written":
                return stage_label
            if phase == "completed":
                return f"{stage_label}: {int(payload.get('scanned', completed) or 0):,}개 파일"
            return stage_label
        if operation == "dry_run_plan":
            if phase == "starting":
                return f"{label} 시작: {int(payload.get('action_count', total) or 0):,}개 대상"
            if phase == "validating":
                return (
                    f"{label} 검증 중: {int(payload.get('action_count', completed) or 0):,}개 검토, "
                    f"차단 {int(payload.get('blocking_count', 0) or 0):,}개"
                )
            if phase == "completed":
                return (
                    f"{label} 완료: {int(payload.get('action_count', completed) or 0):,}개 검토, "
                    f"실행 가능 {bool(payload.get('execute_allowed', False))}"
                )
            return f"{label} 진행 중"
        if phase == "starting" and total:
            return f"{label} 시작: {total:,}개 대상"
        if operation == "hash_missing":
            updated = int(payload.get("updated", 0) or 0)
            attempted = int(payload.get("attempted", completed) or 0)
            if total:
                return f"{label} 진행 중: {attempted:,}/{total:,}개 확인, 갱신 {updated:,}개"
            return f"{label} 진행 중: 확인 {attempted:,}개, 갱신 {updated:,}개"
        if total:
            if failed:
                return f"{label} 진행 중: {completed:,}/{total:,}개 완료, 실패 {failed:,}개"
            return f"{label} 진행 중: {completed:,}/{total:,}개 완료"
        return f"{label} 진행 중"

    def _collect_service_plan_actions(self, service: PhotoOrganizerService, plan_id: int) -> list[OrganizeAction]:
        actions: list[OrganizeAction] = []
        offset = 0
        while True:
            data = self._service_data(
                service.list_plan_actions(plan_id, limit=10_000, offset=offset),
                "서비스 계획 조회",
            )
            rows = data.get("rows", [])
            actions.extend(
                OrganizeAction(str(row["source_path"]), str(row["destination_path"]), "service")
                for row in rows
            )
            offset += len(rows)
            if offset >= int(data.get("total", 0)) or not rows:
                return actions

    def _service_execute_worker(
        self,
        gui_plan: tuple[OrganizeAction, ...],
        source: str,
        destination: str,
        event_threshold: int,
        service_db: str,
    ) -> None:
        try:
            with PhotoOrganizerService(service_db) as service:
                self.after(0, self.status_var.set, "서비스 인벤토리를 스캔하는 중...")
                self._service_data(service.scan_inventory(source), "서비스 인벤토리 스캔")

                self.after(0, self.status_var.set, "서비스 보관 계획을 생성하고 비교하는 중...")
                plan_data = self._service_data(
                    service.create_archive_plan(destination, event_threshold=event_threshold),
                    "서비스 계획 생성",
                )
                plan_id = int(plan_data["plan_id"])
                service_actions = self._collect_service_plan_actions(service, plan_id)
                gui_pairs = self._normalized_plan_pairs(gui_plan)
                service_pairs = self._normalized_plan_pairs(service_actions)
                if gui_pairs != service_pairs:
                    gui_only = sum((gui_pairs - service_pairs).values())
                    service_only = sum((service_pairs - gui_pairs).values())
                    self.after(
                        0,
                        self._finish_service_execution,
                        "서비스 계획 불일치",
                        (
                            "현재 GUI 계획과 서비스 보관 계획이 다르므로 실행을 차단했습니다.\n\n"
                            f"GUI에만 있는 작업: {gui_only:,}건\n"
                            f"서비스에만 있는 작업: {service_only:,}건\n\n"
                            "서비스 계획을 검토한 뒤 GUI 계획을 다시 생성해야 합니다. "
                            "기존 계획 미리보기와 CSV 내보내기는 그대로 사용할 수 있습니다.\n\n"
                            f"서비스 DB: {service_db}"
                        ),
                        True,
                    )
                    return

                dry_run_progress = lambda payload: self.after(
                    0,
                    self.status_var.set,
                    self._service_progress_message(payload),
                )
                initial_dry_run = self._service_data(
                    service.dry_run_plan(plan_id, progress_callback=dry_run_progress),
                    "서비스 dry-run",
                )
                if initial_dry_run.get("blocking_reasons"):
                    reasons = "\n".join(str(item) for item in initial_dry_run["blocking_reasons"][:10])
                    raise RuntimeError(f"서비스 dry-run 차단 사유:\n{reasons}")

                self._service_data(
                    service.approve_plan(plan_id, approved=True, note="root GUI exact-plan-match approval"),
                    "서비스 DB 승인",
                )
                immediate_dry_run = self._service_data(
                    service.dry_run_plan(plan_id, progress_callback=dry_run_progress),
                    "승인 직후 서비스 dry-run",
                )
                gate = self._service_data(service.can_execute(plan_id), "서비스 실행 게이트")
                if immediate_dry_run.get("blocking_reasons") or not gate.get("can_execute"):
                    reasons = immediate_dry_run.get("blocking_reasons") or gate.get("blocking_reasons") or ["실행 게이트 거부"]
                    raise RuntimeError("서비스 실행 게이트 차단 사유:\n" + "\n".join(map(str, reasons[:10])))

                decision = {"approved": False}
                decision_ready = threading.Event()
                self.after(
                    0,
                    self._request_service_runtime_confirmation,
                    len(service_actions),
                    decision,
                    decision_ready,
                )
                decision_ready.wait()
                if not decision["approved"]:
                    self._service_data(
                        service.approve_plan(plan_id, approved=False, note="root GUI runtime confirmation declined"),
                        "서비스 DB 승인 취소",
                    )
                    self.after(0, self._finish_service_execution, "실행 취소", "사용자가 최종 실행을 취소했습니다.", False)
                    return

                final_dry_run = self._service_data(
                    service.dry_run_plan(plan_id, progress_callback=dry_run_progress),
                    "실행 직전 서비스 dry-run",
                )
                final_gate = self._service_data(service.can_execute(plan_id), "실행 직전 서비스 게이트")
                if final_dry_run.get("blocking_reasons") or not final_gate.get("can_execute"):
                    reasons = final_dry_run.get("blocking_reasons") or final_gate.get("blocking_reasons") or ["실행 게이트 거부"]
                    raise RuntimeError("실행 직전 서비스 게이트 차단 사유:\n" + "\n".join(map(str, reasons[:10])))

                executed = self._service_data(
                    service.execute_plan(
                        plan_id,
                        execute_approved=True,
                        progress_callback=lambda payload: self.after(
                            0,
                            self.status_var.set,
                            self._service_progress_message(payload),
                        ),
                    ),
                    "서비스 계획 실행",
                )
                if not executed.get("executed"):
                    reasons = executed.get("blocking_reasons") or ["서비스가 실행하지 않음"]
                    raise RuntimeError("서비스 실행 차단 사유:\n" + "\n".join(map(str, reasons[:10])))
                completed = int(executed.get("completed_count", 0))
                self.after(
                    0,
                    self._finish_service_execution,
                    "서비스 실행 완료",
                    f"서비스를 통해 파일 {completed:,}개 이동을 완료했습니다.",
                    False,
                )
        except Exception as exc:
            self.after(0, self._finish_service_execution, "서비스 실행 차단", str(exc), True)

    def _request_service_runtime_confirmation(
        self,
        action_count: int,
        decision: dict[str, bool],
        decision_ready: threading.Event,
    ) -> None:
        decision["approved"] = messagebox.askyesno(
            "최종 서비스 실행 확인",
            (
                "GUI 계획과 서비스 계획이 정확히 일치하고 승인 직후 실행 게이트를 통과했습니다.\n\n"
                f"서비스를 통해 {action_count:,}개 파일을 실제로 이동할까요?"
            ),
        )
        decision_ready.set()

    def _finish_service_execution(self, title: str, detail: str, warning: bool) -> None:
        self.status_var.set(summarize_service_failure(detail))
        if warning:
            messagebox.showwarning(title, detail)
        else:
            messagebox.showinfo(title, detail)

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
        if element and "indicator" in element.lower():
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
            self._insert_summary_subtree(self.selected_tree, root, "", include_required=True)

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
            self._insert_summary_subtree(self.excluded_tree, root, "", include_required=False)

    def _insert_summary_subtree(self, tree: ttk.Treeview, path: str, parent_id: str, include_required: bool) -> None:
        record = self.folder_map.get(path)
        if not record:
            return
        if include_required and not record.include:
            return
        if not include_required and record.include:
            return
        mark_default = "☑" if include_required else "☐"
        mark = self.folder_state_marks.get(path, mark_default)
        icon = self.icon_checked if mark == "☑" else (self.icon_partial if mark == "▣" else self.icon_unchecked)
        tree.insert(
            parent_id,
            tk.END,
            iid=path,
            text=Path(path).name or path,
            image=icon,
            values=(record.total_files, record.total_photos, format_bytes(record.total_bytes)),
        )
        for child in self.folder_tree_children.get(path, []):
            self._insert_summary_subtree(tree, child, path, include_required)

    def _on_selected_tree_click(self, event) -> None:
        row_id = self.selected_tree.identify_row(event.y)
        if not row_id:
            return
        column = self.selected_tree.identify_column(event.x)
        element = self.selected_tree.identify("element", event.x, event.y)
        if element and "indicator" in element.lower():
            return
        if column == "#0" and element in {"Treeitem.image", "image"}:
            self._toggle_folder_include_by_path(row_id)

    def _on_excluded_tree_click(self, event) -> None:
        row_id = self.excluded_tree.identify_row(event.y)
        if not row_id:
            return
        column = self.excluded_tree.identify_column(event.x)
        element = self.excluded_tree.identify("element", event.x, event.y)
        if element and "indicator" in element.lower():
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
        agg: dict[str, tuple[int, int, str]] = {}
        for action in self.plan:
            destination = Path(action.destination)
            bytes_size = 0
            try:
                bytes_size = os.path.getsize(action.source)
            except OSError:
                pass
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
        self._render_plan_review(root)

    def _render_plan_review(self, root: str, strategy_results: list[dict[str, object]] | None = None) -> None:
        self.plan_review_tree.delete(*self.plan_review_tree.get_children())
        total_files = len(self.plan)
        total_bytes = 0
        for action in self.plan:
            try:
                total_bytes += os.path.getsize(action.source)
            except OSError:
                pass

        mismatches = sum(1 for row in self.date_audit if row.status in {"검토 필요", "강한 불일치", "자동 수정 금지"})
        metadata_missing = sum(1 for row in self.date_audit if row.status == "메타데이터 없음")
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

        if strategy_results:
            compare = self.plan_review_tree.insert("", tk.END, text="전략 비교", values=("",))
            for item in strategy_results:
                label = f"{item['mode']} | {item['scheme']}"
                value = (
                    f"파일 {item['files']:,}, 폴더 {item['folders']:,}, 용량 {format_bytes(int(item['bytes']))}, "
                    f"계획충돌 {item['collisions']:,}, 기존충돌 {item['existing_conflicts']:,}, 불일치 {mismatches:,}"
                )
                self.plan_review_tree.insert(compare, tk.END, text=label, values=(value,))
            self.plan_review_tree.item(compare, open=True)
        self.plan_review_tree.item(summary, open=True)
        self.plan_review_tree.item(criteria, open=True)
        self.plan_review_tree.item(risks, open=True)

    def _review_export_readiness(self) -> tuple[bool, list[str]]:
        missing: list[str] = []
        if not self.has_folder_inventory or not self.folders:
            missing.append("1 또는 1+2 실행으로 폴더 구조/용량 인벤토리를 먼저 만드세요.")
        if not self.has_photo_records or not self.records:
            missing.append("4 사진 메타데이터(또는 빠른 구조 스캔)로 사진 목록을 먼저 만드세요.")
        if not self.has_date_audit or not self.date_audit:
            missing.append("3 날짜 근거를 실행해 날짜 검토 결과를 먼저 만드세요.")
        if not self.has_duplicate_scan:
            missing.append("5 파일명 중복검사 또는 중복 분석을 실행해 중복 판단 정보를 만드세요.")
        return len(missing) == 0, missing

    def _export_review_bundle(self) -> bool:
        ready, missing = self._review_export_readiness()
        if not ready:
            guide = "\n".join(f"- {item}" for item in missing)
            messagebox.showwarning("Review 저장 차단", f"아직 필수 데이터가 부족합니다.\n\n{guide}")
            self.status_var.set(
                f"Review 저장 차단: folders={len(self.folders):,}, records={len(self.records):,}, "
                f"date={len(self.date_audit):,}, clusters={len(self.clusters):,}"
            )
            return False
        review_root = self._review_root()
        review_root.mkdir(parents=True, exist_ok=True)
        folder_csv = review_root / "folder_inventory.csv"
        folder_json = review_root / "folder_inventory.json"
        date_csv = review_root / "date_audit.csv"
        date_json = review_root / "date_audit.json"
        draft_json = review_root / "organize_draft.json"
        review_json = review_root / "composite_review.json"
        review_jsonl = review_root / "composite_review.jsonl"
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
        with open(review_jsonl, "w", encoding="utf-8") as file:
            for row in composite:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")

        chunk_total = 0
        if len(composite) > COMPOSITE_REVIEW_CHUNK_SIZE:
            for start in range(0, len(composite), COMPOSITE_REVIEW_CHUNK_SIZE):
                chunk_total += 1
                chunk_path = review_root / f"composite_review.part{chunk_total:03d}.json"
                with open(chunk_path, "w", encoding="utf-8") as file:
                    json.dump(composite[start : start + COMPOSITE_REVIEW_CHUNK_SIZE], file, ensure_ascii=False, indent=2)

        chunk_info = f", 분할 {chunk_total}개" if chunk_total else ""
        self.status_var.set(
            f"Review 저장 완료: folders={len(self.folders):,}, records={len(self.records):,}, "
            f"date={len(self.date_audit):,}, clusters={len(self.clusters):,}, composite={len(composite):,}{chunk_info}"
        )
        return True

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

        self.review_date_overrides = {}
        self.review_rename_suggestions = {}
        self.review_folder_rename_suggestions = {}
        self.review_duplicate_candidates = []
        self.review_notes = []
        self.review_metadata_suggestions = []

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

        for item in payload.get("exclude_paths", []):
            path = str(item.get("path", "")).strip()
            if not path:
                continue
            lowered = path.lower()
            for record in self.folders:
                record_lower = record.path.lower()
                if record_lower == lowered or record_lower.startswith(lowered + os.sep):
                    record.include = False
                    record.review_status = "검수제외"

        for item in payload.get("date_overrides", []):
            path = str(item.get("path", "")).strip()
            override_date = parse_review_date(item.get("date"))
            if path and override_date:
                self.review_date_overrides[path.lower()] = override_date

        for item in payload.get("rename_suggestions", []):
            path = str(item.get("path", "")).strip()
            new_name = str(item.get("new_name", "")).strip()
            if path and new_name:
                fallback = Path(path).name
                self.review_rename_suggestions[path.lower()] = sanitize_filename_suggestion(new_name, fallback)

        for item in payload.get("folder_rename_suggestions", []):
            path = str(item.get("path", "")).strip()
            new_name = str(item.get("new_name", "")).strip()
            if path and new_name:
                self.review_folder_rename_suggestions[path.lower()] = Path(new_name).name

        for item in payload.get("metadata_edit_suggestions", []):
            if isinstance(item, dict) and item.get("path"):
                self.review_metadata_suggestions.append(item)

        self.review_duplicate_candidates = [item for item in payload.get("duplicate_candidates", []) if isinstance(item, dict)]
        self.review_notes = [str(item) for item in payload.get("notes", []) if str(item).strip()]

        self._reindex_folders()
        self._render_folders()
        self._refresh_duplicate_pair_options()
        summary = (
            f"codex_review 반영 완료: 폴더결정 {len(decisions):,}, 제외경로 {len(payload.get('exclude_paths', [])):,}, "
            f"날짜보정 {len(self.review_date_overrides):,}, 파일명제안 {len(self.review_rename_suggestions):,}, "
            f"폴더명제안 {len(self.review_folder_rename_suggestions):,}, 메타제안 {len(self.review_metadata_suggestions):,}, "
            f"중복후보 {len(self.review_duplicate_candidates):,}"
        )
        self.status_var.set(summary)

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
        path = self.cluster_files.item(selection[0], "values")[1]
        if os.path.exists(path):
            os.startfile(path)

    def _export_duplicate_resolution_plan(self) -> None:
        if not self.has_duplicate_scan:
            messagebox.showinfo("결과 없음", "먼저 파일명 중복검사 또는 중복 분석을 실행하세요.")
            return
        rows: list[dict[str, str]] = []
        for cluster in self.clusters:
            if not cluster.files:
                continue
            keep_path = cluster.files[0].path
            for idx, record in enumerate(cluster.files):
                if cluster.kind == "통합":
                    action = "keep" if idx == 0 else "merge_into_keep"
                    target = keep_path
                elif cluster.kind == "이름정리":
                    action = "rename_required"
                    target = ""
                else:
                    action = "review"
                    target = ""
                rows.append(
                    {
                        "group_kind": cluster.kind,
                        "group_score": cluster.score,
                        "path": record.path,
                        "action": action,
                        "target": target,
                    }
                )
        review_root = self._review_root()
        review_root.mkdir(parents=True, exist_ok=True)
        csv_path = review_root / "duplicate_resolution_plan.csv"
        json_path = review_root / "duplicate_resolution_plan.json"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["group_kind", "group_score", "path", "action", "target"])
            for row in rows:
                writer.writerow([row["group_kind"], row["group_score"], row["path"], row["action"], row["target"]])
        with open(json_path, "w", encoding="utf-8") as file:
            json.dump(rows, file, ensure_ascii=False, indent=2)
        self.status_var.set(f"중복 처리계획 저장 완료: {len(rows):,}건 ({csv_path.name}, {json_path.name})")

    def _clear_trees(self) -> None:
        self.folder_tree.delete(*self.folder_tree.get_children())
        self.selected_tree.delete(*self.selected_tree.get_children())
        self.excluded_tree.delete(*self.excluded_tree.get_children())
        self.date_tree.delete(*self.date_tree.get_children())
        if hasattr(self, "bulk_tree"):
            self.bulk_tree.delete(*self.bulk_tree.get_children())
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
        date_map = {record.path: record for record in self.date_audit}
        cluster_map: dict[str, str] = {}
        for cluster in self.clusters:
            for record in cluster.files:
                cluster_map[record.path] = cluster.kind
        folder_role_map = {record.path: record.role for record in self.folders}
        tag_rows: list[dict[str, str]] = []
        for record in self.records:
            parent = str(Path(record.path).parent)
            date_row = date_map.get(record.path)
            tags = [
                f"year:{record.best_date:%Y}",
                f"month:{record.best_date:%m}",
                f"date_source:{record.date_source}",
            ]
            role = folder_role_map.get(parent, "")
            if role:
                tags.append(f"folder_role:{role}")
            if date_row and date_row.status:
                tags.append(f"date_status:{date_row.status}")
            duplicate_kind = cluster_map.get(record.path, "")
            if duplicate_kind:
                tags.append(f"duplicate:{duplicate_kind}")
            if record.place and record.place != "Unscanned":
                tags.append(f"place:{record.place}")
            tag_rows.append(
                {
                    "path": record.path,
                    "tags": "|".join(tags),
                }
            )
        tags_csv = review_root / "photo_tags.csv"
        tags_json = review_root / "photo_tags.json"
        with open(tags_csv, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["path", "tags"])
            for row in tag_rows:
                writer.writerow([row["path"], row["tags"]])
        with open(tags_json, "w", encoding="utf-8") as file:
            json.dump(tag_rows, file, ensure_ascii=False, indent=2)
        if self.review_metadata_suggestions:
            metadata_json = review_root / "metadata_edit_plan.json"
            metadata_csv = review_root / "metadata_edit_plan.csv"
            payload = {
                "mode": "plan_only",
                "write_enabled": False,
                "requires_manual_verification": True,
                "items": self.review_metadata_suggestions,
            }
            with open(metadata_json, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
            with open(metadata_csv, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(["path", "action", "proposed", "status"])
                for item in self.review_metadata_suggestions:
                    writer.writerow([item.get("path", ""), item.get("action", ""), item.get("proposed", ""), "manual_review_required"])


def main() -> int:
    app = PhotoOrganizerApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
