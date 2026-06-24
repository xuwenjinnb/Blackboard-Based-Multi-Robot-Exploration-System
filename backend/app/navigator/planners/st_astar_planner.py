from __future__ import annotations

from heapq import heappop, heappush
from typing import Any

from ...config import SimulationConfig
from ...pathfinding import Point, heading_between, in_bounds, manhattan, neighbors4, point_key


def st_astar(
    map_grid: dict[str, Any],
    start: Point,
    goal: Point,
    *,
    reservations: dict[int, set[tuple[int, int]]] | None = None,
    edge_reservations: set[tuple[tuple[int, int], tuple[int, int], int]] | None = None,
    max_time: int = 96,
    goal_safe_until: int | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    width = int(map_grid["width"])
    height = int(map_grid["height"])
    cells = {(int(cell["x"]), int(cell["y"])): cell for cell in map_grid["cells"]}
    start_key = point_key(start)
    goal_key = point_key(goal)
    reservations = reservations or {}
    edge_reservations = edge_reservations or set()

    if not in_bounds(start_key, width, height) or not in_bounds(goal_key, width, height):
        return [], "start or goal is outside the map"

    goal_cell = cells.get(goal_key)
    if goal_cell and goal_cell.get("state") in {"OBSTACLE", "RESERVED"}:
        return [], "goal is blocked"

    start_state = (start_key[0], start_key[1], 0)
    open_set: list[tuple[float, int, tuple[int, int, int]]] = []
    counter = 0
    heappush(open_set, (manhattan(start, goal), counter, start_state))
    parents: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    g_score: dict[tuple[int, int, int], float] = {start_state: 0.0}
    visited: set[tuple[int, int, int]] = set()

    while open_set:
        _, _, current = heappop(open_set)
        if current in visited:
            continue
        visited.add(current)

        current_cell = (current[0], current[1])
        current_time = current[2]
        if current_cell == goal_key and goal_is_safe_until(current_cell, current_time, reservations, goal_safe_until):
            raw_path = reconstruct_time_path(parents, current)
            return to_steps_with_time(raw_path), None

        if current_time >= max_time:
            continue

        for neighbor in neighbors4(current_cell) + [current_cell]:
            next_time = current_time + 1
            if not in_bounds(neighbor, width, height):
                continue
            if is_reserved(neighbor, next_time, reservations):
                continue
            if (neighbor, current_cell, next_time) in edge_reservations:
                continue

            cell = cells.get(neighbor)
            state = cell.get("state", "UNKNOWN") if cell else "UNKNOWN"
            if state in {"OBSTACLE", "RESERVED"}:
                continue

            step_cost = 1.0
            if neighbor == current_cell:
                step_cost = 1.0
            elif state == "UNKNOWN":
                step_cost = 3.0
            elif state == "VISITED":
                step_cost = 0.8

            next_state = (neighbor[0], neighbor[1], next_time)
            tentative_g = g_score[current] + step_cost
            if tentative_g >= g_score.get(next_state, float("inf")):
                continue

            parents[next_state] = current
            g_score[next_state] = tentative_g
            counter += 1
            h = abs(neighbor[0] - goal_key[0]) + abs(neighbor[1] - goal_key[1])
            heappush(open_set, (tentative_g + h, counter, next_state))

    return [], "no time-safe path found"


def goal_is_safe_until(
    goal: tuple[int, int],
    current_time: int,
    reservations: dict[int, set[tuple[int, int]]],
    goal_safe_until: int | None,
) -> bool:
    if goal_safe_until is None:
        return True
    for time_slot in range(current_time, goal_safe_until + 1):
        if goal in reservations.get(time_slot, set()):
            return False
    return True


def is_reserved(
    cell: tuple[int, int],
    time_slot: int,
    reservations: dict[int, set[tuple[int, int]]],
) -> bool:
    return cell in reservations.get(time_slot, set())


def reconstruct_time_path(
    parents: dict[tuple[int, int, int], tuple[int, int, int]],
    current: tuple[int, int, int],
) -> list[tuple[int, int, int]]:
    path = [current]
    while current in parents:
        current = parents[current]
        path.append(current)
    path.reverse()
    return path


def to_steps_with_time(raw_path: list[tuple[int, int, int]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for index, point in enumerate(raw_path):
        previous = raw_path[index - 1] if index > 0 else point
        current_xy = (point[0], point[1])
        previous_xy = (previous[0], previous[1])
        action = "WAIT" if current_xy == previous_xy and index > 0 else "MOVE"
        steps.append(
            {
                "stepIndex": index,
                "position": {"x": point[0], "y": point[1]},
                "heading": heading_between(previous_xy, current_xy),
                "expectedTimeSlot": point[2],
                "action": action,
            }
        )
    return steps


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
        excluded_vehicle_ids: set[str] = set()
        for task in snapshot["tasks"]:
            if task["taskId"] == exclude_task_id:
                if task.get("vehicleId"):
                    excluded_vehicle_ids.add(str(task["vehicleId"]))
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
            if str(vehicle.get("vehicleId", "")) in excluded_vehicle_ids:
                continue
            if vehicle.get("currentTaskId") in active_task_ids:
                continue
            position = vehicle.get("pose", {}).get("position")
            if not isinstance(position, dict):
                continue
            cell = (int(position["x"]), int(position["y"]))
            for offset in range(0, horizon + 1):
                reservations.setdefault(offset, set()).add(cell)

        return reservations, edge_reservations
