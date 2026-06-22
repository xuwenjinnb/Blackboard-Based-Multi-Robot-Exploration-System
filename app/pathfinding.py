from __future__ import annotations

from heapq import heappop, heappush
from typing import Any, Dict


Point = Dict[str, int]


def point_key(point: Point) -> tuple[int, int]:
    return int(point["x"]), int(point["y"])


def manhattan(a: Point, b: Point) -> int:
    return abs(int(a["x"]) - int(b["x"])) + abs(int(a["y"]) - int(b["y"]))


def heading_between(a: tuple[int, int], b: tuple[int, int]) -> int:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if dx > 0:
        return 0
    if dy > 0:
        return 90
    if dx < 0:
        return 180
    if dy < 0:
        return 270
    return 0


def reconstruct_path(
    parents: dict[tuple[int, int], tuple[int, int]],
    current: tuple[int, int],
) -> list[tuple[int, int]]:
    path = [current]
    while current in parents:
        current = parents[current]
        path.append(current)
    path.reverse()
    return path


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


def in_bounds(point: tuple[int, int], width: int, height: int) -> bool:
    return 0 <= point[0] < width and 0 <= point[1] < height


def neighbors4(point: tuple[int, int]) -> list[tuple[int, int]]:
    x, y = point
    return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]


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


def to_steps(raw_path: list[tuple[int, int]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for index, point in enumerate(raw_path):
        previous = raw_path[index - 1] if index > 0 else point
        heading = heading_between(previous, point)
        steps.append(
            {
                "stepIndex": index,
                "position": {"x": point[0], "y": point[1]},
                "heading": heading,
                "expectedTimeSlot": index,
                "action": "MOVE",
            }
        )
    return steps


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
