from __future__ import annotations

from typing import Any

from ...visibility import visible_points_in_square


def unknown_cells_visible_from(
    position: dict[str, int],
    cell_map: dict[tuple[int, int], dict[str, Any]],
    scan_radius: int,
) -> int:
    """输入 frontier 坐标和地图格子，输出扫描半径内可见 UNKNOWN 格子数量。"""
    origin = point_tuple(position)
    return sum(
        1
        for point in visible_points_in_square(
            origin,
            scan_radius,
            in_bounds=lambda candidate: candidate in cell_map,
            is_blocked=lambda candidate: (
                cell_map.get(candidate, {}).get("state") == "OBSTACLE"
            ),
        )
        if cell_map.get(point, {}).get("state") == "UNKNOWN"
    )


def point_tuple(point: dict[str, int]) -> tuple[int, int]:
    return int(point["x"]), int(point["y"])


def occupied_positions(snapshot: dict[str, Any]) -> set[tuple[int, int]]:
    """输入黑板快照，输出当前车辆位置和未完成任务目标占用的坐标集合。"""
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
