from __future__ import annotations

from typing import Any

from ...redis import Blackboard, now_ms
from ...config import SimulationConfig
from ...pathfinding import manhattan
from ...controller.policies.helpers import unknown_cells_visible_from
from ...visibility import visible_points_in_square


MAX_FRONTIERS_PER_SCAN = 16


class FrontierScanAlgorithm:
    """Local scan, map patch upload, and frontier detection for robot exploration."""

    low_level_policy_names = {"low_mdp", "low-mdp", "low-level-mdp", "low_level_mdp"}

    def __init__(self, blackboard: Blackboard, config: SimulationConfig) -> None:
        self.blackboard = blackboard
        self.config = config

    @property
    def scan_radius(self) -> int:
        return self.config.scan_radius

    @property
    def frontier_search_radius(self) -> int:
        return self.config.frontier_search_radius

    @property
    def detects_frontiers_by_default(self) -> bool:
        return self.config.policy.strip().lower() not in self.low_level_policy_names

    def scan_and_upload(self, vehicle_id: str, *, detect_frontiers: bool | None = None) -> None:
        snapshot = self.blackboard.snapshot_view()
        vehicle = next((item for item in snapshot["vehicles"] if item["vehicleId"] == vehicle_id), None)
        if not vehicle:
            return
        center = vehicle["pose"]["position"]
        center_point = point_tuple(center)
        timestamp = now_ms()
        cells = []
        is_blocked = lambda point: self.blackboard.is_truth_blocked(
            {"x": point[0], "y": point[1]}
        )
        for x, y in visible_points_in_square(
            center_point,
            self.scan_radius,
            in_bounds=lambda point: (
                0 <= point[0] < self.blackboard.width
                and 0 <= point[1] < self.blackboard.height
            ),
            is_blocked=is_blocked,
        ):
            if is_blocked((x, y)):
                state = "OBSTACLE"
            elif (x, y) == center_point:
                state = "VISITED"
            else:
                state = "FREE"
            cells.append(
                {
                    "x": x,
                    "y": y,
                    "state": state,
                    "confidence": 1.0,
                    "updatedAt": timestamp,
                }
            )
        self.blackboard.upload_map_patch(
            {
                "patchId": self.blackboard.next_id("patch"),
                "vehicleId": vehicle_id,
                "baseMapVersion": snapshot["map"]["version"],
                "cells": cells,
                "timestamp": now_ms(),
            }
        )
        if detect_frontiers is None:
            detect_frontiers = self.detects_frontiers_by_default
        if detect_frontiers:
            self.detect_frontiers(vehicle_id, center, self.frontier_search_radius)

    def detect_frontiers(self, vehicle_id: str, center: dict[str, int], radius: int) -> None:
        snapshot = self.blackboard.snapshot_view()
        width = int(snapshot["map"].get("width", self.blackboard.width))
        height = int(snapshot["map"].get("height", self.blackboard.height))
        cell_map = {(cell["x"], cell["y"]): cell for cell in snapshot["map"]["cells"]}
        candidates: list[tuple[float, int, int, int]] = []
        for y in range(center["y"] - radius, center["y"] + radius + 1):
            for x in range(center["x"] - radius, center["x"] + radius + 1):
                if not (0 <= x < width and 0 <= y < height):
                    continue
                cell = cell_map.get((x, y))
                if not cell or cell.get("state") not in {"FREE", "VISITED"}:
                    continue
                if not self.has_unknown_neighbor({"x": x, "y": y}, cell_map):
                    continue

                unknown_gain = self.unknown_cells_visible_from({"x": x, "y": y}, cell_map)
                if unknown_gain <= 0:
                    continue

                distance_penalty = 0.15 * manhattan(center, {"x": x, "y": y})
                rank_score = unknown_gain * 10.0 - distance_penalty
                candidates.append((rank_score, unknown_gain, x, y))

        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        for _rank_score, unknown_gain, x, y in candidates[:MAX_FRONTIERS_PER_SCAN]:
            try:
                self.blackboard.save_frontier(
                    {
                        "position": {"x": x, "y": y},
                        "unknownGain": unknown_gain,
                        "discoveredBy": vehicle_id,
                        "status": "OPEN",
                        "timestamp": now_ms(),
                    }
                )
            except ValueError:
                continue

    def unknown_cells_visible_from(
        self,
        position: dict[str, int],
        cell_map: dict[tuple[int, int], dict[str, Any]],
    ) -> int:
        return unknown_cells_visible_from(position, cell_map, self.scan_radius)

    def has_unknown_neighbor(
        self,
        position: dict[str, int],
        cell_map: dict[tuple[int, int], dict[str, Any]],
    ) -> bool:
        return any(
            cell_map.get(neighbor, {}).get("state") == "UNKNOWN"
            for neighbor in neighbors8(point_tuple(position))
        )


def point_tuple(point: dict[str, int]) -> tuple[int, int]:
    return int(point["x"]), int(point["y"])


def neighbors4(point: tuple[int, int]) -> list[tuple[int, int]]:
    x, y = point
    return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]


def neighbors8(point: tuple[int, int]) -> list[tuple[int, int]]:
    x, y = point
    return [
        (x + dx, y + dy)
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if dx != 0 or dy != 0
    ]


def neighbors4_with_wait(point: tuple[int, int]) -> list[tuple[int, int]]:
    return neighbors4(point) + [point]
