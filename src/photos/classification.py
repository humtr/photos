from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from .database import record_classification_result


def import_classification_csv(con: sqlite3.Connection, csv_path: str | Path) -> int:
    """Import external person/non-person classifier output.

    Expected columns: path,label. Optional columns: confidence,model,note.
    The importer does not move or delete files.
    """
    imported = 0
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        has_required_fields = (
            reader.fieldnames
            and "path" in reader.fieldnames
            and "label" in reader.fieldnames
        )
        if not has_required_fields:
            raise ValueError("classification CSV must include path and label columns")
        for row in reader:
            path = (row.get("path") or "").strip()
            label = (row.get("label") or "").strip()
            if not path or not label:
                continue
            confidence_text = (row.get("confidence") or "").strip()
            confidence = float(confidence_text) if confidence_text else None
            record_classification_result(
                con,
                path=path,
                label=label,
                confidence=confidence,
                model=(row.get("model") or "").strip(),
                details={"note": (row.get("note") or "").strip()},
            )
            imported += 1
    return imported
