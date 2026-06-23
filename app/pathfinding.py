"""Shared grid utilities; navigator algorithms live in app.navigator.planners."""

from __future__ import annotations

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
    from .navigator.planners.astar_planner import astar as planner_astar

    return planner_astar(map_grid, start, goal)


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
    from .navigator.planners.st_astar_planner import st_astar as planner_st_astar

    return planner_st_astar(
        map_grid,
        start,
        goal,
        reservations=reservations,
        edge_reservations=edge_reservations,
        max_time=max_time,
        goal_safe_until=goal_safe_until,
    )


def in_bounds(point: tuple[int, int], width: int, height: int) -> bool:
    return 0 <= point[0] < width and 0 <= point[1] < height


def neighbors4(point: tuple[int, int]) -> list[tuple[int, int]]:
    x, y = point
    return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]


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
