from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

RAW_EXTENSIONS = {".arw", ".raf", ".cr2", ".cr3", ".dng"}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}
IMAGE_EXTENSIONS = JPEG_EXTENSIONS | {".png", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".mts", ".m2ts"}
SUPPORTED_MEDIA_EXTENSIONS = RAW_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


@dataclass(frozen=True)
class MediaRecord:
    root: str
    path: str
    rel_path: str
    parent_key: str
    name: str
    stem_key: str
    suffix: str
    media_type: str
    size_bytes: int
    mtime_ns: int
    sha256: str | None = None


@dataclass(frozen=True)
class RawJpgPair:
    raw_path: str
    jpg_path: str
    confidence: str
    reason: str


def media_type_for_path(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    name = Path(path).name.lower()
    if suffix in RAW_EXTENSIONS:
        return "raw"
    if suffix in JPEG_EXTENSIONS:
        return "jpeg"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in IMAGE_EXTENSIONS:
        if "screenshot" in name or "screen shot" in name:
            return "screenshot"
        return "image"
    return "other"


def is_supported_media(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_MEDIA_EXTENSIONS
