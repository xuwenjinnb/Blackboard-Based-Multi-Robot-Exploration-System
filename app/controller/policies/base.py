from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from typing import Protocol
except ImportError:  # Python < 3.8 compatibility for older conda envs.
    class Protocol:
        pass


@dataclass(frozen=True)
class AssignmentDecision:
    vehicle_id: str
    frontier_id: str
    priority: int = 5
    score: float = 0.0


class AssignmentPolicy(Protocol):
    name: str

    def select_assignments(
        self,
        snapshot: dict[str, Any],
        vehicles: list[dict[str, Any]],
        frontiers: list[dict[str, Any]],
        *,
        scan_radius: int,
    ) -> list[AssignmentDecision]:
        ...
