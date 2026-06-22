from __future__ import annotations

from typing import Any

from .base import AssignmentDecision


class NoopAssignmentPolicy:
    name = "noop"

    def select_assignments(
        self,
        snapshot: dict[str, Any],
        vehicles: list[dict[str, Any]],
        frontiers: list[dict[str, Any]],
        *,
        scan_radius: int,
    ) -> list[AssignmentDecision]:
        del snapshot, vehicles, frontiers, scan_radius
        return []
