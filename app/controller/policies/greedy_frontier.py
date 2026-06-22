from __future__ import annotations

from typing import Any

from ...pathfinding import manhattan
from .base import AssignmentDecision
from .helpers import unknown_cells_visible_from


class GreedyFrontierPolicy:
    name = "greedy-frontier"

    def __init__(self, gain_weight: float = 10.0, distance_weight: float = 0.35) -> None:
        self.gain_weight = gain_weight
        self.distance_weight = distance_weight

    def select_assignments(
        self,
        snapshot: dict[str, Any],
        vehicles: list[dict[str, Any]],
        frontiers: list[dict[str, Any]],
        *,
        scan_radius: int,
    ) -> list[AssignmentDecision]:
        available = list(frontiers)
        decisions: list[AssignmentDecision] = []
        cell_map = {(cell["x"], cell["y"]): cell for cell in snapshot["map"]["cells"]}

        for vehicle in vehicles:
            best = self.choose_frontier(vehicle, available, cell_map, scan_radius)
            if best is None:
                continue
            decisions.append(
                AssignmentDecision(
                    vehicle_id=vehicle["vehicleId"],
                    frontier_id=best["frontier"]["frontierId"],
                    score=best["score"],
                )
            )
            available = [
                item for item in available if item["frontierId"] != best["frontier"]["frontierId"]
            ]
            if not available:
                break

        return decisions

    def choose_frontier(
        self,
        vehicle: dict[str, Any],
        frontiers: list[dict[str, Any]],
        cell_map: dict[tuple[int, int], dict[str, Any]],
        scan_radius: int,
    ) -> dict[str, Any] | None:
        if not frontiers:
            return None

        position = vehicle["pose"]["position"]
        scored = []
        for frontier in frontiers:
            current_gain = unknown_cells_visible_from(frontier["position"], cell_map, scan_radius)
            if current_gain <= 0:
                continue
            distance = manhattan(position, frontier["position"])
            score = current_gain * self.gain_weight - self.distance_weight * distance
            scored.append({"score": score, "frontier": frontier})

        if not scored:
            return None
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[0]
