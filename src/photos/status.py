from __future__ import annotations

from .store import Store


def status_summary(store: Store) -> dict:
    row_plan = store.conn.execute("select id, status from organize_plans order by id desc limit 1").fetchone()
    row_batch = store.conn.execute("select id, status from execution_batches order by id desc limit 1").fetchone()
    return {
        "latest_plan": dict(row_plan) if row_plan else None,
        "latest_batch": dict(row_batch) if row_batch else None,
    }
