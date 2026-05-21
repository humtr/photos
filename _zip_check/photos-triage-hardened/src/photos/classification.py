from __future__ import annotations

import csv
import math
import sqlite3
from pathlib import Path

from .database import record_classification_result


def import_classification_csv(con: sqlite3.Connection, csv_path: str | Path) -> int:
    """Import external person/non-person classifier output.

    Expected columns: path,label. Optional columns: confidence,model,note.
    The importer does not move or delete files and commits once after all rows
    have been validated.
    """
    pending: list[tuple[str, str, float | None, str, dict[str, str]]] = []
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        has_required_fields = (
            reader.fieldnames
            and "path" in reader.fieldnames
            and "label" in reader.fieldnames
        )
        if not has_required_fields:
            raise ValueError("classification CSV must include path and label columns")
        for row_number, row in enumerate(reader, start=2):
            path = (row.get("path") or "").strip()
            label = (row.get("label") or "").strip()
            if not path or not label:
                continue
            confidence_text = (row.get("confidence") or "").strip()
            confidence = float(confidence_text) if confidence_text else None
            if confidence is not None and not math.isfinite(confidence):
                raise ValueError(f"invalid confidence on row {row_number} for {path}: {confidence_text}")
            pending.append(
                (
                    path,
                    label,
                    confidence,
                    (row.get("model") or "").strip(),
                    {"note": (row.get("note") or "").strip()},
                )
            )

    for path, label, confidence, model, details in pending:
        record_classification_result(
            con,
            path=path,
            label=label,
            confidence=confidence,
            model=model,
            details=details,
            commit=False,
        )
    con.commit()
    return len(pending)
