from __future__ import annotations

from typing import Any

from ...config import SimulationConfig
from ...pathfinding import st_astar


class StAStarPlanner:
    name = "st_astar"

    def __init__(self, config: SimulationConfig) -> None:
        self.config = config

    def plan(self, snapshot: dict[str, Any], request: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        reservations, edge_reservations = self.build_time_reservations(
            snapshot,
            exclude_task_id=request["taskId"],
            horizon=self.config.st_astar_horizon,
        )
        return st_astar(
            snapshot["map"],
            request["start"],
            request["goal"],
            reservations=reservations,
            edge_reservations=edge_reservations,
            max_time=self.config.st_astar_horizon,
        )

    def build_time_reservations(
        self,
        snapshot: dict[str, Any],
        *,
        exclude_task_id: str | None = None,
        horizon: int = 96,
    ) -> tuple[dict[int, set[tuple[int, int]]], set[tuple[tuple[int, int], tuple[int, int], int]]]:
        reservations: dict[int, set[tuple[int, int]]] = {}
        edge_reservations: set[tuple[tuple[int, int], tuple[int, int], int]] = set()

        active_task_ids: set[str] = set()
        for task in snapshot["tasks"]:
            if task["taskId"] == exclude_task_id:
                continue
            if task.get("status") in {"DONE", "FAILED", "CANCELLED"}:
                continue
            path = task.get("pathQueue") or []
            if not path:
                continue
            active_task_ids.add(task["taskId"])
            current_index = int(task.get("currentStepIndex", 0))
            future = path[current_index:]
            previous: tuple[int, int] | None = None
            for offset, step in enumerate(future[: horizon + 1]):
                cell = (int(step["position"]["x"]), int(step["position"]["y"]))
                reservations.setdefault(offset, set()).add(cell)
                if previous is not None:
                    edge_reservations.add((previous, cell, offset))
                previous = cell

            if previous is not None:
                for offset in range(len(future), horizon + 1):
                    reservations.setdefault(offset, set()).add(previous)

        for vehicle in snapshot["vehicles"]:
            if vehicle.get("currentTaskId") in active_task_ids:
                continue
            position = vehicle["pose"]["position"]
            reservations.setdefault(0, set()).add((int(position["x"]), int(position["y"])))

        return reservations, edge_reservations
