from __future__ import annotations

from .store import Store


def approve_plan_execute(store: Store, plan_id: int, note: str = "") -> int:
    return store.add_approval("execute", "plan", plan_id, True, note)


def is_plan_execute_approved(store: Store, plan_id: int) -> bool:
    return store.is_approved("execute", "plan", plan_id)
