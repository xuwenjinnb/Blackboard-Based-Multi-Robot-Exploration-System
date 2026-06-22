from __future__ import annotations

from typing import Any

from ...pathfinding import astar, manhattan
from .base import AssignmentDecision
from .helpers import occupied_positions, point_tuple, unknown_cells_visible_from


class NearestReachableFrontierPolicy:
    name = "nearest-reachable-frontier"

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
        occupied = occupied_positions(snapshot)
        cell_map = {(cell["x"], cell["y"]): cell for cell in snapshot["map"]["cells"]}

        for vehicle in vehicles:
            start = vehicle["pose"]["position"]
            blocked_positions = set(occupied)
            blocked_positions.discard(point_tuple(start))
            selected = self.nearest_reachable_frontier(
                snapshot["map"],
                start,
                available,
                blocked_positions,
                cell_map,
                scan_radius,
            )
            if selected is None:
                continue

            frontier = selected["frontier"]
            decisions.append(
                AssignmentDecision(
                    vehicle_id=vehicle["vehicleId"],
                    frontier_id=frontier["frontierId"],
                    score=-float(selected["distance"]),
                )
            )
            available = [item for item in available if item["frontierId"] != frontier["frontierId"]]
            occupied.add(point_tuple(frontier["position"]))
            if not available:
                break

        return decisions

    def nearest_reachable_frontier(
        self,
        map_grid: dict[str, Any],
        start: dict[str, int],
        frontiers: list[dict[str, Any]],
        occupied: set[tuple[int, int]],
        cell_map: dict[tuple[int, int], dict[str, Any]],
        scan_radius: int,
    ) -> dict[str, Any] | None:
        reachable: list[dict[str, Any]] = []
        for frontier in frontiers:
            position = frontier["position"]
            if point_tuple(position) in occupied:
                continue
            if unknown_cells_visible_from(position, cell_map, scan_radius) <= 0:
                continue
            path, _ = astar(map_grid, start, position)
            if not path:
                continue
            reachable.append(
                {
                    "frontier": frontier,
                    "distance": max(0, len(path) - 1),
                    "manhattan": manhattan(start, position),
                }
            )

        if not reachable:
            return None

        reachable.sort(key=lambda item: (item["distance"], item["manhattan"]))
        return {
            "frontier": reachable[0]["frontier"],
            "distance": reachable[0]["distance"],
        }
