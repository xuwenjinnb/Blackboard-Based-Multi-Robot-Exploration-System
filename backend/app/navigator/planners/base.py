from __future__ import annotations

from typing import Any, Protocol


class PlannerProtocol(Protocol):
    name: str

    def plan(self, snapshot: dict[str, Any], request: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        ...
