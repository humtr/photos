from __future__ import annotations

import ctypes
import shutil
from pathlib import Path


def _drive_root(path: Path) -> str:
    resolved = str(path.resolve())
    if len(resolved) >= 2 and resolved[1] == ":":
        return resolved[:3]
    return str(path.anchor or path)


def get_volume_identity(path: Path) -> str:
    root = _drive_root(path)
    if hasattr(ctypes, "windll") and root:
        serial = ctypes.c_uint(0)
        max_component_len = ctypes.c_uint(0)
        fs_flags = ctypes.c_uint(0)
        volume_name = ctypes.create_unicode_buffer(260)
        fs_name = ctypes.create_unicode_buffer(260)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root),
            volume_name,
            260,
            ctypes.byref(serial),
            ctypes.byref(max_component_len),
            ctypes.byref(fs_flags),
            fs_name,
            260,
        )
        if ok:
            return f"{root.lower()}#{serial.value:x}"
    return root.lower()


def is_same_volume(source: Path, destination_root: Path) -> bool:
    return get_volume_identity(source) == get_volume_identity(destination_root)


def free_space_bytes(path: Path) -> int:
    return int(shutil.disk_usage(path).free)
