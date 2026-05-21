from pathlib import Path

# Make `photos.*` resolve to modules implemented under `src/photos`.
_SRC_PHOTOS = Path(__file__).resolve().parents[1] / "src" / "photos"
if str(_SRC_PHOTOS) not in __path__:
    __path__.append(str(_SRC_PHOTOS))

