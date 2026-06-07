from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class ServiceResult:
    """Stable response envelope for GUI, CLI, and automation callers.

    Frontends should branch on ``ok`` and ``next_safe_action`` instead of parsing
    exception text. Backends should keep this envelope backward-compatible.
    """

    ok: bool
    command: str
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_safe_action: str = "idle"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Page:
    page: int
    page_size: int
    total: int
    rows: list[dict[str, Any]]

    @property
    def has_next(self) -> bool:
        return self.page * self.page_size < self.total

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["has_next"] = self.has_next
        return data


def ok(
    command: str,
    data: Mapping[str, Any] | None = None,
    *,
    warnings: Iterable[str] = (),
    next_safe_action: str = "idle",
) -> dict[str, Any]:
    return ServiceResult(
        ok=True,
        command=command,
        data=dict(data or {}),
        warnings=list(warnings),
        next_safe_action=next_safe_action,
    ).to_dict()


def fail(
    command: str,
    error: BaseException | str,
    *,
    data: Mapping[str, Any] | None = None,
    warnings: Iterable[str] = (),
    next_safe_action: str = "inspect_errors",
) -> dict[str, Any]:
    message = str(error) if isinstance(error, str) else repr(error)
    return ServiceResult(
        ok=False,
        command=command,
        data=dict(data or {}),
        errors=[message],
        warnings=list(warnings),
        next_safe_action=next_safe_action,
    ).to_dict()


def row_to_dict(row: Any) -> dict[str, Any]:
    """Convert sqlite3.Row or mapping-like objects into JSON-friendly dicts."""

    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    return dict(row)
