from __future__ import annotations

import importlib
from types import ModuleType


def _load_root_gui() -> ModuleType:
    try:
        return importlib.import_module("photo_organizer_app")
    except ModuleNotFoundError as exc:
        if exc.name == "photo_organizer_app":
            raise RuntimeError(
                "The Photo Organizer GUI module is not installed. "
                "Reinstall photos-triage 0.2.0 or run from the repository root."
            ) from exc
        if exc.name in {"tkinter", "_tkinter"}:
            raise RuntimeError(
                "Tkinter is unavailable. Install a Python build with Tk support to run the GUI."
            ) from exc
        raise
    except ImportError as exc:
        if "tkinter" in str(exc).lower() or "_tkinter" in str(exc).lower():
            raise RuntimeError(
                "Tkinter is unavailable. Install a Python build with Tk support to run the GUI."
            ) from exc
        raise


def launch() -> int:
    root_gui = _load_root_gui()
    main = getattr(root_gui, "main", None)
    if not callable(main):
        raise RuntimeError(
            "The installed Photo Organizer GUI module does not expose main(). Reinstall photos-triage."
        )
    return main()
