from __future__ import annotations

from typing import Any

from ...config import SimulationConfig
from ...pathfinding import astar


class AStarPlanner:
    name = "astar"

    def __init__(self, config: SimulationConfig) -> None:
        self.config = config

    def plan(self, snapshot: dict[str, Any], request: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        return astar(snapshot["map"], request["start"], request["goal"])
