from __future__ import annotations

import copy
from heapq import heappop, heappush
from typing import Any

from ...config import SimulationConfig
from ...pathfinding import point_key
from .st_astar_planner import st_astar


class CBSPlanner:
    name = "cbs"

    def __init__(self, config: SimulationConfig) -> None:
        self.config = config

    def plan_batch(
        self,
        snapshot: dict[str, Any],
        requests: list[dict[str, Any]],
    ) -> dict[str, tuple[list[dict[str, Any]], str | None]]:
        if not requests:
            return {}

        request_by_vehicle = {request["vehicleId"]: request for request in requests}
        group_task_ids = {request["taskId"] for request in requests}
        fixed_reservations, fixed_edges = self.fixed_reservations(snapshot, group_task_ids)

        initial_solution: dict[str, list[dict[str, Any]]] = {}
        results: dict[str, tuple[list[dict[str, Any]], str | None]] = {}
        for request in requests:
            path, reason = self.low_level_search(
                snapshot,
                request,
                [],
                fixed_reservations,
                fixed_edges,
            )
            if path:
                initial_solution[request["vehicleId"]] = path
            else:
                results[request["requestId"]] = ([], reason or "no CBS low-level path")

        if not initial_solution:
            return results

        open_set: list[tuple[int, int, list[dict[str, Any]], dict[str, list[dict[str, Any]]]]] = []
        counter = 0
        heappush(open_set, (self.solution_cost(initial_solution), counter, [], initial_solution))
        expanded = 0

        while open_set and expanded < self.config.cbs_max_nodes:
            _, _, constraints, solution = heappop(open_set)
            expanded += 1
            conflict = self.detect_conflict(solution)
            if conflict is None:
                for vehicle_id, path in solution.items():
                    request = request_by_vehicle[vehicle_id]
                    results[request["requestId"]] = (path, None)
                return results

            for vehicle_id in (conflict["a"], conflict["b"]):
                request = request_by_vehicle[vehicle_id]
                child_constraints = constraints + [self.constraint_for(conflict, vehicle_id)]
                path, reason = self.low_level_search(
                    snapshot,
                    request,
                    child_constraints,
                    fixed_reservations,
                    fixed_edges,
                )
                if not path:
                    continue

                child_solution = copy.deepcopy(solution)
                child_solution[vehicle_id] = path
                counter += 1
                heappush(
                    open_set,
                    (
                        self.solution_cost(child_solution),
                        counter,
                        child_constraints,
                        child_solution,
                    ),
                )

        for vehicle_id in initial_solution:
            request = request_by_vehicle[vehicle_id]
            results.setdefault(
                request["requestId"],
                ([], f"CBS conflict resolution limit reached after {expanded} nodes"),
            )
        return results

    def low_level_search(
        self,
        snapshot: dict[str, Any],
        request: dict[str, Any],
        constraints: list[dict[str, Any]],
        fixed_reservations: dict[int, set[tuple[int, int]]],
        fixed_edges: set[tuple[tuple[int, int], tuple[int, int], int]],
    ) -> tuple[list[dict[str, Any]], str | None]:
        reservations = {time: set(cells) for time, cells in fixed_reservations.items()}
        edge_reservations = set(fixed_edges)
        goal_safe_until: int | None = None
        start = point_key(request["start"])

        for constraint in constraints:
            if constraint["vehicleId"] != request["vehicleId"]:
                continue
            time_slot = int(constraint["time"])
            goal_safe_until = max(goal_safe_until or 0, time_slot)
            if constraint["type"] == "vertex":
                cell = tuple(constraint["cell"])
                if time_slot == 0 and cell == start:
                    return [], "start is constrained at t=0"
                reservations.setdefault(time_slot, set()).add(cell)
            elif constraint["type"] == "edge":
                edge_reservations.add(
                    (
                        tuple(constraint["to"]),
                        tuple(constraint["from"]),
                        time_slot,
                    )
                )

        return st_astar(
            snapshot["map"],
            request["start"],
            request["goal"],
            reservations=reservations,
            edge_reservations=edge_reservations,
            max_time=self.config.st_astar_horizon,
            goal_safe_until=goal_safe_until,
        )

    def detect_conflict(self, paths: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
        vehicle_ids = sorted(paths)
        if len(vehicle_ids) < 2:
            return None
        max_len = max(len(path) for path in paths.values())

        for time_slot in range(max_len):
            occupied: dict[tuple[int, int], str] = {}
            for vehicle_id in vehicle_ids:
                cell = self.position_at(paths[vehicle_id], time_slot)
                if cell in occupied:
                    return {
                        "type": "vertex",
                        "a": occupied[cell],
                        "b": vehicle_id,
                        "cell": cell,
                        "time": time_slot,
                    }
                occupied[cell] = vehicle_id

        for time_slot in range(1, max_len):
            for index, vehicle_a in enumerate(vehicle_ids):
                for vehicle_b in vehicle_ids[index + 1 :]:
                    a_from = self.position_at(paths[vehicle_a], time_slot - 1)
                    a_to = self.position_at(paths[vehicle_a], time_slot)
                    b_from = self.position_at(paths[vehicle_b], time_slot - 1)
                    b_to = self.position_at(paths[vehicle_b], time_slot)
                    if a_from == b_to and a_to == b_from and a_from != a_to:
                        return {
                            "type": "edge",
                            "a": vehicle_a,
                            "b": vehicle_b,
                            "time": time_slot,
                            "edges": {
                                vehicle_a: (a_from, a_to),
                                vehicle_b: (b_from, b_to),
                            },
                        }
        return None

    def constraint_for(self, conflict: dict[str, Any], vehicle_id: str) -> dict[str, Any]:
        if conflict["type"] == "vertex":
            return {
                "type": "vertex",
                "vehicleId": vehicle_id,
                "cell": conflict["cell"],
                "time": conflict["time"],
            }

        edge_from, edge_to = conflict["edges"][vehicle_id]
        return {
            "type": "edge",
            "vehicleId": vehicle_id,
            "from": edge_from,
            "to": edge_to,
            "time": conflict["time"],
        }

    def fixed_reservations(
        self,
        snapshot: dict[str, Any],
        group_task_ids: set[str],
    ) -> tuple[dict[int, set[tuple[int, int]]], set[tuple[tuple[int, int], tuple[int, int], int]]]:
        reservations: dict[int, set[tuple[int, int]]] = {}
        edge_reservations: set[tuple[tuple[int, int], tuple[int, int], int]] = set()
        active_task_ids: set[str] = set()

        for task in snapshot["tasks"]:
            if task["taskId"] in group_task_ids:
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
            for offset, step in enumerate(future[: self.config.st_astar_horizon + 1]):
                cell = point_key(step["position"])
                reservations.setdefault(offset, set()).add(cell)
                if previous is not None:
                    edge_reservations.add((previous, cell, offset))
                previous = cell

            if previous is not None:
                for offset in range(len(future), self.config.st_astar_horizon + 1):
                    reservations.setdefault(offset, set()).add(previous)

        for vehicle in snapshot["vehicles"]:
            current_task_id = vehicle.get("currentTaskId")
            if current_task_id in active_task_ids or current_task_id in group_task_ids:
                continue
            reservations.setdefault(0, set()).add(point_key(vehicle["pose"]["position"]))

        return reservations, edge_reservations

    @staticmethod
    def position_at(path: list[dict[str, Any]], time_slot: int) -> tuple[int, int]:
        index = min(time_slot, len(path) - 1)
        return point_key(path[index]["position"])

    @staticmethod
    def solution_cost(solution: dict[str, list[dict[str, Any]]]) -> int:
        return sum(max(0, len(path) - 1) for path in solution.values())
