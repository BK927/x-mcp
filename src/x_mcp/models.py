from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation: str
    target: str = ""
    query: str = ""
    sort: str = "latest"
    limit: int = Field(default=10, ge=1, le=50)

    def fingerprint(self) -> str:
        # Page size and rendering detail do not change the underlying selection.
        data = self.model_dump(exclude={"limit"})
        return hashlib.sha256(dumps(data).encode()).hexdigest()


@dataclass
class ProviderPage:
    provider: str
    items: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] | None = None
    next_cursor: str | None = None
    retrieved_at: str = field(default_factory=utc_now)
    warnings: list[str] = field(default_factory=list)
    completeness: str = "source_page"


class Output(BaseModel):
    """Small shared output schema, rather than eight copies of all X object schemas."""

    data: dict[str, Any] | None = None
    items: list[dict[str, Any]] | None = None
    page: dict[str, Any] | None = None
    result_id: str | None = None
    meta: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
