from __future__ import annotations

from heapq import heappop, heappush
from typing import Any

from ...config import SimulationConfig
from ...pathfinding import Point, in_bounds, neighbors4, point_key, reconstruct_path, to_steps


def astar(map_grid: dict[str, Any], start: Point, goal: Point) -> tuple[list[dict[str, Any]], str | None]:
    width = int(map_grid["width"])
    height = int(map_grid["height"])
    cells = {(int(cell["x"]), int(cell["y"])): cell for cell in map_grid["cells"]}
    start_key = point_key(start)
    goal_key = point_key(goal)

    if not in_bounds(start_key, width, height) or not in_bounds(goal_key, width, height):
        return [], "start or goal is outside the map"

    goal_cell = cells.get(goal_key)
    if goal_cell and goal_cell.get("state") in {"OBSTACLE", "RESERVED"}:
        return [], "goal is blocked"

    open_set: list[tuple[float, int, tuple[int, int]]] = []
    counter = 0
    heappush(open_set, (0, counter, start_key))
    parents: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], float] = {start_key: 0}
    visited: set[tuple[int, int]] = set()

    while open_set:
        _, _, current = heappop(open_set)
        if current in visited:
            continue
        visited.add(current)

        if current == goal_key:
            raw_path = reconstruct_path(parents, current)
            return to_steps(raw_path), None

        for neighbor in neighbors4(current):
            if not in_bounds(neighbor, width, height):
                continue

            cell = cells.get(neighbor)
            state = cell.get("state", "UNKNOWN") if cell else "UNKNOWN"
            if state in {"OBSTACLE", "RESERVED"}:
                continue

            step_cost = 1.0
            if state == "UNKNOWN":
                step_cost = 3.0
            elif state == "FREE":
                step_cost = 1.0
            elif state == "VISITED":
                step_cost = 0.8

            tentative_g = g_score[current] + step_cost
            if tentative_g >= g_score.get(neighbor, float("inf")):
                continue

            parents[neighbor] = current
            g_score[neighbor] = tentative_g
            counter += 1
            h = abs(neighbor[0] - goal_key[0]) + abs(neighbor[1] - goal_key[1])
            heappush(open_set, (tentative_g + h, counter, neighbor))

    return [], "no path found"


class AStarPlanner:
    name = "astar"

    def __init__(self, config: SimulationConfig) -> None:
        self.config = config

    def plan(self, snapshot: dict[str, Any], request: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        return astar(snapshot["map"], request["start"], request["goal"])
