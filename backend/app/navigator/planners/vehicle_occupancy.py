from __future__ import annotations

import copy
from typing import Any

from ...pathfinding import point_key


def map_with_vehicle_reservations(
    map_grid: dict[str, Any],
    vehicles: list[dict[str, Any]],
    *,
    exclude_vehicle_id: str | None = None,
) -> dict[str, Any]:
    reserved_by_position: dict[tuple[int, int], str] = {}
    for vehicle in vehicles:
        vehicle_id = str(vehicle.get("vehicleId", ""))
        if exclude_vehicle_id is not None and vehicle_id == exclude_vehicle_id:
            continue
        pose = vehicle.get("pose") or {}
        position = pose.get("position")
        if not isinstance(position, dict):
            continue
        try:
            reserved_by_position[point_key(position)] = vehicle_id
        except (KeyError, TypeError, ValueError):
            continue

    if not reserved_by_position:
        return map_grid

    overlay = {
        key: value
        for key, value in map_grid.items()
        if key != "chunks"
    }
    cells = [copy.deepcopy(cell) for cell in map_grid.get("cells", [])]
    for cell in cells:
        try:
            point = (int(cell["x"]), int(cell["y"]))
        except (KeyError, TypeError, ValueError):
            continue
        vehicle_id = reserved_by_position.get(point)
        if vehicle_id is None or cell.get("state") == "OBSTACLE":
            continue
        cell["baseState"] = cell.get("state", "UNKNOWN")
        cell["state"] = "RESERVED"
        cell["confidence"] = 1.0
        cell["reservedBy"] = vehicle_id

    overlay["cells"] = cells
    return overlay
