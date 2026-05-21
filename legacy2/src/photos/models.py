from __future__ import annotations

from dataclasses import dataclass


MEDIA_EXTENSIONS = {
    ".jpg": "photo",
    ".jpeg": "photo",
    ".png": "photo",
    ".webp": "photo",
    ".heic": "photo",
    ".gif": "photo",
    ".bmp": "photo",
    ".tif": "photo",
    ".tiff": "photo",
    ".arw": "photo",
    ".raf": "photo",
    ".dng": "photo",
    ".mp4": "video",
    ".mov": "video",
    ".avi": "video",
    ".mkv": "video",
}

ATTENTION_PATTERNS = {
    ".thumbnail": "cache_thumbnail",
    "thumb": "cache_thumbnail",
    "$recycle.bin": "system_recycle_bin",
    "system volume information": "system_volume_info",
    ".sync": "sync_folder",
    "onedrive": "sync_folder",
}

EXISTENCE_SEEN = "seen"
EXISTENCE_NOT_SEEN = "not_seen_this_scan"
EXISTENCE_MISSING = "confirmed_missing"


@dataclass(frozen=True)
class GPSPoint:
    lat: float
    lon: float
