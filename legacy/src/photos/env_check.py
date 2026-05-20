from __future__ import annotations

import importlib.util
import json
import platform
import shutil
import sys

RAW_TOOL_CANDIDATES = ["darktable-cli", "rawtherapee-cli", "magick"]


def check_environment() -> dict:
    tools = {
        "git": shutil.which("git"),
        "ffmpeg": shutil.which("ffmpeg"),
        "exiftool": shutil.which("exiftool"),
    }
    raw_tools = {name: shutil.which(name) for name in RAW_TOOL_CANDIDATES}
    return {
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "tools": tools,
        "raw_tool_candidates": raw_tools,
        "pyside6_available": importlib.util.find_spec("PySide6") is not None,
    }


def main(argv: list[str] | None = None) -> int:
    _ = argv
    print(json.dumps(check_environment(), indent=2, sort_keys=True))
    return 0
