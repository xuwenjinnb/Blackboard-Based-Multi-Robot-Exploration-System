from __future__ import annotations

from collections.abc import Callable, Iterable


GridPoint = tuple[int, int]


def has_line_of_sight(
    origin: GridPoint,
    target: GridPoint,
    is_blocked: Callable[[GridPoint], bool],
) -> bool:
    """Return whether target is visible from origin on a square grid.

    A blocking cell remains visible itself, but cells behind the first
    blocker on the same ray are hidden. At an exact grid corner, either side
    cell blocks the ray so vision cannot leak diagonally around wall corners.
    """
    if origin == target:
        return True

    x, y = origin
    target_x, target_y = target
    delta_x = target_x - x
    delta_y = target_y - y
    step_x = 1 if delta_x > 0 else -1 if delta_x < 0 else 0
    step_y = 1 if delta_y > 0 else -1 if delta_y < 0 else 0
    t_delta_x = 1.0 / abs(delta_x) if delta_x else float("inf")
    t_delta_y = 1.0 / abs(delta_y) if delta_y else float("inf")
    t_max_x = 0.5 * t_delta_x
    t_max_y = 0.5 * t_delta_y

    while (x, y) != target:
        if t_max_x < t_max_y:
            x += step_x
            t_max_x += t_delta_x
        elif t_max_y < t_max_x:
            y += step_y
            t_max_y += t_delta_y
        else:
            side_x = (x + step_x, y)
            side_y = (x, y + step_y)
            if (
                (side_x != target and is_blocked(side_x))
                or (side_y != target and is_blocked(side_y))
            ):
                return False
            x += step_x
            y += step_y
            t_max_x += t_delta_x
            t_max_y += t_delta_y

        point = (x, y)
        if point == target:
            return True
        if is_blocked(point):
            return False

    return True


def visible_points_in_square(
    origin: GridPoint,
    radius: int,
    *,
    in_bounds: Callable[[GridPoint], bool],
    is_blocked: Callable[[GridPoint], bool],
) -> Iterable[GridPoint]:
    """Yield in-range cells that are not occluded from origin."""
    origin_x, origin_y = origin
    for y in range(origin_y - radius, origin_y + radius + 1):
        for x in range(origin_x - radius, origin_x + radius + 1):
            point = (x, y)
            if in_bounds(point) and has_line_of_sight(origin, point, is_blocked):
                yield point
