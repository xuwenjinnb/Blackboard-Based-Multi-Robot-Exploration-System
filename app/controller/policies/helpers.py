from __future__ import annotations

from typing import Any


def unknown_cells_visible_from(
    position: dict[str, int],
    cell_map: dict[tuple[int, int], dict[str, Any]],
    scan_radius: int,
) -> int:
    gain = 0
    for y in range(position["y"] - scan_radius, position["y"] + scan_radius + 1):
        for x in range(position["x"] - scan_radius, position["x"] + scan_radius + 1):
            cell = cell_map.get((x, y))
            if cell and cell.get("state") == "UNKNOWN":
                gain += 1
    return gain


def point_tuple(point: dict[str, int]) -> tuple[int, int]:
    return int(point["x"]), int(point["y"])


def occupied_positions(snapshot: dict[str, Any]) -> set[tuple[int, int]]:
    occupied = {
        point_tuple(vehicle["pose"]["position"])
        for vehicle in snapshot.get("vehicles", [])
        if vehicle.get("pose")
    }
    occupied.update(
        point_tuple(task["target"])
        for task in snapshot.get("tasks", [])
        if task.get("status") not in {"DONE", "FAILED", "CANCELLED"} and task.get("target")
    )
    return occupied
