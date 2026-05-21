from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Message:
    code: str
    message: str
    phase: str | None = None
    path: str | None = None
    recoverable: bool | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.phase is not None:
            data["phase"] = self.phase
        if self.path is not None:
            data["path"] = self.path
        if self.recoverable is not None:
            data["recoverable"] = self.recoverable
        return data


def envelope(
    command: str,
    db: str,
    started_at: str,
    ok: bool = True,
    summary: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    warnings: list[Message] | None = None,
    errors: list[Message] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": ok,
        "command": command,
        "db": db,
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "summary": summary or {},
        "artifacts": artifacts or [],
        "warnings": [w.to_json() for w in (warnings or [])],
        "errors": [e.to_json() for e in (errors or [])],
    }


@dataclass(slots=True)
class DryRunResult:
    schema_version: int = 1
    plan_id: int = 0
    batch_id: int | None = None
    error_count: int = 0
    execute_allowed: bool = False
    blocking_reasons: list[str] = field(default_factory=list)
    batch_summaries: list[dict[str, Any]] = field(default_factory=list)
    capacity_checks: list[dict[str, Any]] = field(default_factory=list)
    transfer_method: str = "same_volume_move"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "batch_id": self.batch_id,
            "error_count": self.error_count,
            "execute_allowed": self.execute_allowed,
            "blocking_reasons": self.blocking_reasons,
            "batch_summaries": self.batch_summaries,
            "capacity_checks": self.capacity_checks,
            "transfer_method": self.transfer_method,
        }


@dataclass(slots=True)
class ExecuteResult:
    schema_version: int = 1
    plan_id: int = 0
    batch_id: int = 0
    transfer_method: str = "same_volume_move"
    committed_count: int = 0
    failed_count: int = 0
    held_count: int = 0
    manifest_path: str = ""
    manifest_sha256: str = ""
    next_safe_action: str = "review_failures"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "batch_id": self.batch_id,
            "transfer_method": self.transfer_method,
            "committed_count": self.committed_count,
            "failed_count": self.failed_count,
            "held_count": self.held_count,
            "manifest_path": self.manifest_path,
            "manifest_sha256": self.manifest_sha256,
            "next_safe_action": self.next_safe_action,
        }
