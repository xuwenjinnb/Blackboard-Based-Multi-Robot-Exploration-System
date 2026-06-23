from __future__ import annotations

import copy
import random
import threading
import time
from contextlib import contextmanager
from typing import Any

from ..visibility import visible_points_in_square

MAX_MAP_DIMENSION = 512
MAX_CHUNK_SIZE = 128
MAP_DELTA_HISTORY_LIMIT = 120
INACTIVE_FRONTIER_HISTORY_LIMIT = 160
COMPLETED_TASK_HISTORY_LIMIT = 48
NAVIGATION_HISTORY_LIMIT = 96


def now_ms() -> int:
    return int(time.time() * 1000)


class Blackboard:
    def __init__(self, width: int = 50, height: int = 50, chunk_size: int = 10) -> None:
        self.width = self._normalize_dimension(width, "width")
        self.height = self._normalize_dimension(height, "height")
        self.chunk_size = self._normalize_chunk_size(chunk_size)
        self.lock = threading.RLock()
        self._map_delta_log: list[dict[str, Any]] = []
        self.reset()

    @contextmanager
    def batch(self):
        with self.lock:
            yield self

    def reset(self) -> None:
        with self.lock:
            timestamp = now_ms()
            self._clear_map_delta_log_locked()
            previous_generation = int(getattr(self, "_map_generation", 0))
            self._map_generation = max(timestamp, previous_generation + 1)
            self.map = self._build_map(self._build_empty_cells(timestamp), version=1, updated_at=timestamp)
            self.true_obstacles = self._build_truth_obstacles()
            self.vehicles: dict[str, dict[str, Any]] = {}
            self.tasks: dict[str, dict[str, Any]] = {}
            self.frontiers: dict[str, dict[str, Any]] = {}
            self.navigation_requests: dict[str, dict[str, Any]] = {}
            self.navigation_plans: dict[str, dict[str, Any]] = {}
            self.heartbeats: dict[str, dict[str, Any]] = {}
            self.events: list[dict[str, Any]] = []
            self.system_status = "STOPPED"
            self._counters = {
                "event": 0,
                "task": 0,
                "frontier": 0,
                "request": 0,
                "plan": 0,
                "patch": 0,
            }
            self.add_event("system", "SYSTEM_CONTROL", "Blackboard reset")

    @staticmethod
    def _normalize_dimension(value: int, name: str) -> int:
        dimension = int(value)
        if dimension < 3:
            raise ValueError(f"map {name} must be at least 3")
        if dimension > MAX_MAP_DIMENSION:
            raise ValueError(f"map {name} must be at most {MAX_MAP_DIMENSION}")
        return dimension

    @staticmethod
    def _normalize_chunk_size(value: int) -> int:
        chunk_size = int(value)
        if chunk_size < 2:
            raise ValueError("chunk size must be at least 2")
        if chunk_size > MAX_CHUNK_SIZE:
            raise ValueError(f"chunk size must be at most {MAX_CHUNK_SIZE}")
        return chunk_size

    def _build_empty_cells(self, timestamp: int) -> list[dict[str, Any]]:
        return [
            {
                "x": x,
                "y": y,
                "state": "UNKNOWN",
                "confidence": 0.0,
                "updatedBy": "system",
                "updatedAt": timestamp,
            }
            for y in range(self.height)
            for x in range(self.width)
        ]

    def _point_in_bounds(self, point: tuple[int, int]) -> bool:
        return 0 <= point[0] < self.width and 0 <= point[1] < self.height

    def _build_map(
        self,
        cells: list[dict[str, Any]],
        *,
        version: int,
        updated_at: int,
        map_id: str = "demo-map",
    ) -> dict[str, Any]:
        normalized_cells = self._normalize_cells_for_map(cells, updated_at)
        return {
            "mapId": map_id,
            "width": self.width,
            "height": self.height,
            "chunkSize": self.chunk_size,
            "version": version,
            "generation": getattr(self, "_map_generation", updated_at),
            "cells": normalized_cells,
            "chunks": self._build_chunks_from_cells(normalized_cells),
            "updatedAt": updated_at,
        }

    def _normalize_cells_for_map(self, cells: list[dict[str, Any]], timestamp: int) -> list[dict[str, Any]]:
        by_point: dict[tuple[int, int], dict[str, Any]] = {}
        for incoming in cells:
            try:
                x = int(incoming["x"])
                y = int(incoming["y"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= x < self.width and 0 <= y < self.height):
                continue

            cell = copy.deepcopy(incoming)
            cell["x"] = x
            cell["y"] = y
            cell.setdefault("state", "UNKNOWN")
            cell.setdefault("confidence", 0.0)
            cell.setdefault("updatedBy", "system")
            cell.setdefault("updatedAt", timestamp)
            by_point[(x, y)] = cell

        normalized: list[dict[str, Any]] = []
        for y in range(self.height):
            for x in range(self.width):
                cell = by_point.get((x, y))
                if cell is None:
                    cell = {
                        "x": x,
                        "y": y,
                        "state": "UNKNOWN",
                        "confidence": 0.0,
                        "updatedBy": "system",
                        "updatedAt": timestamp,
                    }
                normalized.append(cell)
        return normalized

    def _build_chunks_from_cells(self, cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_point = {
            (int(cell["x"]), int(cell["y"])): cell
            for cell in cells
        }
        chunks: list[dict[str, Any]] = []
        for origin_y in range(0, self.height, self.chunk_size):
            for origin_x in range(0, self.width, self.chunk_size):
                chunk_width = min(self.chunk_size, self.width - origin_x)
                chunk_height = min(self.chunk_size, self.height - origin_y)
                chunk_cells = [
                    by_point[(x, y)]
                    for y in range(origin_y, origin_y + chunk_height)
                    for x in range(origin_x, origin_x + chunk_width)
                ]
                chunks.append(
                    {
                        "chunkId": self._chunk_id(origin_x // self.chunk_size, origin_y // self.chunk_size),
                        "origin": {"x": origin_x, "y": origin_y},
                        "width": chunk_width,
                        "height": chunk_height,
                        "cells": chunk_cells,
                    }
                )
        return chunks

    def _cells_from_chunks(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not chunks:
            return []
        timestamp = max(
            (
                int(cell.get("updatedAt", 0))
                for chunk in chunks
                for cell in chunk.get("cells", [])
            ),
            default=now_ms(),
        )
        by_point = {
            (int(cell["x"]), int(cell["y"])): copy.deepcopy(cell)
            for chunk in chunks
            for cell in chunk.get("cells", [])
            if 0 <= int(cell.get("x", -1)) < self.width
            and 0 <= int(cell.get("y", -1)) < self.height
        }
        for cell in self._build_empty_cells(timestamp or now_ms()):
            by_point.setdefault((int(cell["x"]), int(cell["y"])), cell)
        cells = list(by_point.values())
        cells.sort(key=lambda cell: (int(cell["y"]), int(cell["x"])))
        return cells

    def _rebuild_map_chunks_locked(self) -> None:
        self.map["chunkSize"] = self.chunk_size
        self.map["chunks"] = self._build_chunks_from_cells(self.map["cells"])

    def _clear_map_delta_log_locked(self) -> None:
        self._map_delta_log = []

    def _chunk_id_for_cell(self, cell: dict[str, Any]) -> str:
        return self._chunk_id(int(cell["x"]) // self.chunk_size, int(cell["y"]) // self.chunk_size)

    def _record_map_delta_locked(self, from_version: int, changed_cells: list[dict[str, Any]]) -> None:
        if not changed_cells:
            return
        latest_by_point = {
            (int(cell["x"]), int(cell["y"])): copy.deepcopy(cell)
            for cell in changed_cells
        }
        cells = sorted(latest_by_point.values(), key=lambda cell: (int(cell["y"]), int(cell["x"])))
        self._map_delta_log.append(
            {
                "fromVersion": int(from_version),
                "toVersion": int(self.map["version"]),
                "generation": int(self.map.get("generation", 0)),
                "cells": cells,
                "chunkIds": sorted({self._chunk_id_for_cell(cell) for cell in cells}),
            }
        )
        self._map_delta_log = self._map_delta_log[-MAP_DELTA_HISTORY_LIMIT:]

    def _map_delta_since_locked(
        self,
        map_version: int,
        map_generation: int | None = None,
    ) -> dict[str, Any] | None:
        current_version = int(self.map["version"])
        base_version = int(map_version)
        current_generation = int(self.map.get("generation", 0))
        if map_generation is not None and int(map_generation) != current_generation:
            return None
        if base_version == current_version:
            return {
                "fromVersion": base_version,
                "toVersion": current_version,
                "generation": current_generation,
                "cells": [],
                "chunkIds": [],
                "changedCellCount": 0,
            }
        if base_version < 0 or base_version > current_version:
            return None

        records: list[dict[str, Any]] = []
        cursor = base_version
        for record in self._map_delta_log:
            if int(record["toVersion"]) <= base_version:
                continue
            if int(record["fromVersion"]) != cursor:
                return None
            records.append(record)
            cursor = int(record["toVersion"])
            if cursor == current_version:
                break
        if cursor != current_version:
            return None

        latest_by_point: dict[tuple[int, int], dict[str, Any]] = {}
        chunk_ids: set[str] = set()
        for record in records:
            chunk_ids.update(record.get("chunkIds", []))
            for cell in record.get("cells", []):
                latest_by_point[(int(cell["x"]), int(cell["y"]))] = copy.deepcopy(cell)
        cells = sorted(latest_by_point.values(), key=lambda cell: (int(cell["y"]), int(cell["x"])))
        return {
            "fromVersion": base_version,
            "toVersion": current_version,
            "generation": current_generation,
            "cells": cells,
            "chunkIds": sorted(chunk_ids),
            "changedCellCount": len(cells),
        }

    @staticmethod
    def _map_metadata(map_data: dict[str, Any]) -> dict[str, Any]:
        return {
            key: copy.deepcopy(value)
            for key, value in map_data.items()
            if key not in {"cells", "chunks"}
        }

    @staticmethod
    def _chunk_id(chunk_x: int, chunk_y: int) -> str:
        return f"{chunk_x}:{chunk_y}"

    def configure_map(self, *, width: int, height: int, chunk_size: int | None = None) -> dict[str, Any]:
        with self.lock:
            self.width = self._normalize_dimension(width, "width")
            self.height = self._normalize_dimension(height, "height")
            if chunk_size is not None:
                self.chunk_size = self._normalize_chunk_size(chunk_size)
            self.reset()
            self.add_event(
                "controller",
                "MAP_CONFIGURED",
                f"Map configured to {self.width}x{self.height} with {self.chunk_size}x{self.chunk_size} chunks",
            )
            return {
                "width": self.width,
                "height": self.height,
                "chunkSize": self.chunk_size,
                "mapVersion": self.map["version"],
                "chunks": len(self.map["chunks"]),
            }

    def _build_truth_obstacles(self) -> set[tuple[int, int]]:
        obstacles: set[tuple[int, int]] = set()
        def add_if_in_bounds(x: int, y: int) -> None:
            if 0 <= x < self.width and 0 <= y < self.height:
                obstacles.add((x, y))

        for x in range(self.width):
            add_if_in_bounds(x, 0)
            add_if_in_bounds(x, self.height - 1)
        for y in range(self.height):
            add_if_in_bounds(0, y)
            add_if_in_bounds(self.width - 1, y)
        for y in range(4, 20):
            if y not in {8, 16}:
                add_if_in_bounds(12, y)
        for x in range(8, 28):
            if x not in {15, 23}:
                add_if_in_bounds(x, 10)
        for y in range(2, 15):
            if y != 6:
                add_if_in_bounds(22, y)
        return obstacles

    def _build_border_obstacles(self) -> set[tuple[int, int]]:
        obstacles: set[tuple[int, int]] = set()
        for x in range(self.width):
            obstacles.add((x, 0))
            obstacles.add((x, self.height - 1))
        for y in range(self.height):
            obstacles.add((0, y))
            obstacles.add((self.width - 1, y))
        return obstacles

    def _build_random_obstacles(
        self,
        density: float,
        seed: int | None = None,
        protected_points: set[tuple[int, int]] | None = None,
        count: int | None = None,
    ) -> set[tuple[int, int]]:
        rng = random.Random(seed)
        all_points = [
            (x, y)
            for y in range(self.height)
            for x in range(self.width)
        ]
        if not all_points:
            return set()

        protected = {
            (int(x), int(y))
            for x, y in (protected_points or set())
            if 0 <= int(x) < self.width and 0 <= int(y) < self.height
        }
        if count is None:
            density = max(0.0, min(0.85, float(density)))
            requested_count = int(len(all_points) * density)
        else:
            requested_count = int(count)
        max_obstacle_count = max(0, len(all_points) - max(1, len(protected)))
        obstacle_count = min(max_obstacle_count, max(0, requested_count))
        obstacles: set[tuple[int, int]] = set()
        free: set[tuple[int, int]] = set(all_points)
        candidates = [point for point in all_points if point not in protected]
        rng.shuffle(candidates)

        # Prefer isolated obstacles first, then gradually relax the local-density
        # limit. This keeps random layouts scattered while every accepted change
        # still preserves one connected free-space component.
        remaining = candidates
        for max_adjacent_obstacles in range(9):
            if len(obstacles) >= obstacle_count or not remaining:
                break
            next_remaining: list[tuple[int, int]] = []
            for point in remaining:
                if len(obstacles) >= obstacle_count:
                    next_remaining.append(point)
                    continue
                if self._obstacle_neighbor_count(point, obstacles) > max_adjacent_obstacles:
                    next_remaining.append(point)
                    continue
                free.remove(point)
                obstacles.add(point)
                if self._free_space_connected(free):
                    continue
                obstacles.remove(point)
                free.add(point)
                next_remaining.append(point)
            remaining = next_remaining

        return obstacles

    def _connect_protected_points(
        self,
        free: set[tuple[int, int]],
        protected: set[tuple[int, int]],
        rng: random.Random,
    ) -> None:
        for target in sorted(protected):
            if target in free:
                continue
            source = rng.choice(tuple(free))
            x, y = source
            tx, ty = target
            horizontal_first = bool(rng.randrange(2))
            if horizontal_first:
                self._carve_axis_path(free, x, tx, y, axis="x")
                self._carve_axis_path(free, y, ty, tx, axis="y")
            else:
                self._carve_axis_path(free, y, ty, x, axis="y")
                self._carve_axis_path(free, x, tx, ty, axis="x")

    @staticmethod
    def _carve_axis_path(
        free: set[tuple[int, int]],
        start: int,
        end: int,
        fixed: int,
        *,
        axis: str,
    ) -> None:
        step = 1 if end >= start else -1
        for value in range(start, end + step, step):
            if axis == "x":
                free.add((value, fixed))
            else:
                free.add((fixed, value))

    def _touches_free(self, point: tuple[int, int], free: set[tuple[int, int]]) -> bool:
        return any(neighbor in free for neighbor in self._neighbors4(point))

    def _neighbors4(self, point: tuple[int, int]) -> list[tuple[int, int]]:
        x, y = point
        return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]

    def _neighbors8(self, point: tuple[int, int]) -> list[tuple[int, int]]:
        x, y = point
        return [
            (x + dx, y + dy)
            for dy in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if dx or dy
        ]

    def _obstacle_neighbor_count(
        self,
        point: tuple[int, int],
        obstacles: set[tuple[int, int]],
    ) -> int:
        return sum(1 for neighbor in self._neighbors8(point) if neighbor in obstacles)

    def _free_space_connected(self, free: set[tuple[int, int]]) -> bool:
        if not free:
            return False
        start = next(iter(free))
        reachable = {start}
        frontier = [start]
        while frontier:
            point = frontier.pop()
            for neighbor in self._neighbors4(point):
                if neighbor in free and neighbor not in reachable:
                    reachable.add(neighbor)
                    frontier.append(neighbor)
        return len(reachable) == len(free)

    def configure_obstacles(
        self,
        *,
        mode: str,
        obstacles: list[dict[str, Any]] | None = None,
        density: float = 0.18,
        seed: int | None = None,
        protected_points: set[tuple[int, int]] | None = None,
        count: int | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            normalized = (mode or "manual").strip().lower()
            protected = {
                (int(x), int(y))
                for x, y in (protected_points or set())
                if 0 <= int(x) < self.width and 0 <= int(y) < self.height
            }
            if normalized == "random":
                points = self._build_random_obstacles(density, seed, protected, count)
            elif normalized == "manual":
                points = set()
            elif normalized == "custom":
                points = set()
                for item in obstacles or []:
                    x = int(item["x"])
                    y = int(item["y"])
                    if 0 <= x < self.width and 0 <= y < self.height:
                        points.add((x, y))
            else:
                raise ValueError(f"unknown obstacle mode: {mode}")

            points.difference_update(protected)
            self.true_obstacles = points
            changed = self._apply_obstacles_to_map_locked(points)
            self.clear_runtime_state_locked()
            self.add_event(
                "controller",
                "OBSTACLES_CONFIGURED",
                f"{normalized} obstacle layout configured: {len(points)} blocked cells",
            )
            return {
                "mode": normalized,
                "count": len(points),
                "changed": changed,
                "mapVersion": self.map["version"],
            }

    def set_obstacle_at(self, x: int, y: int, blocked: bool | None = None) -> dict[str, Any]:
        with self.lock:
            x = int(x)
            y = int(y)
            if not (0 <= x < self.width and 0 <= y < self.height):
                raise ValueError("cell is outside the map")

            point = (x, y)
            next_blocked = point not in self.true_obstacles if blocked is None else bool(blocked)
            if next_blocked:
                for vehicle in self.vehicles.values():
                    position = vehicle.get("pose", {}).get("position", {})
                    if int(position.get("x", -1)) == x and int(position.get("y", -1)) == y:
                        raise ValueError("cell is occupied by a vehicle")
            if next_blocked:
                self.true_obstacles.add(point)
            else:
                self.true_obstacles.discard(point)

            changed = self._apply_obstacles_to_map_locked(self.true_obstacles)
            self.clear_runtime_state_locked()
            self.add_event(
                "controller",
                "OBSTACLE_TOGGLED",
                f"Obstacle {'added' if next_blocked else 'removed'} at ({x}, {y})",
            )
            return {
                "x": x,
                "y": y,
                "blocked": next_blocked,
                "changed": changed,
                "mapVersion": self.map["version"],
            }

    def set_obstacles_at(self, cells: list[dict[str, Any]]) -> dict[str, Any]:
        with self.lock:
            changed_points: list[dict[str, Any]] = []
            for item in cells or []:
                x = int(item["x"])
                y = int(item["y"])
                if not (0 <= x < self.width and 0 <= y < self.height):
                    raise ValueError("cell is outside the map")

                point = (x, y)
                next_blocked = point not in self.true_obstacles if item.get("blocked") is None else bool(item["blocked"])
                if next_blocked:
                    for vehicle in self.vehicles.values():
                        position = vehicle.get("pose", {}).get("position", {})
                        if int(position.get("x", -1)) == x and int(position.get("y", -1)) == y:
                            raise ValueError("cell is occupied by a vehicle")

                was_blocked = point in self.true_obstacles
                if next_blocked:
                    self.true_obstacles.add(point)
                else:
                    self.true_obstacles.discard(point)
                if was_blocked != next_blocked:
                    changed_points.append({"x": x, "y": y, "blocked": next_blocked})

            changed = self._apply_obstacles_to_map_locked(self.true_obstacles)
            if changed_points:
                self.clear_runtime_state_locked()
                self.add_event(
                    "controller",
                    "OBSTACLES_BRUSHED",
                    f"{len(changed_points)} obstacles brushed",
                )
            return {
                "cells": changed_points,
                "changed": changed,
                "mapVersion": self.map["version"],
            }

    def clear_runtime_state_locked(self, *, keep_vehicles: bool = False) -> None:
        if not keep_vehicles:
            self.vehicles = {}
        self.tasks = {}
        self.frontiers = {}
        self.navigation_requests = {}
        self.navigation_plans = {}
        self.heartbeats = {}
        self.system_status = "STOPPED"

    def reset_perception_map_locked(self) -> int:
        return self._apply_obstacles_to_map_locked(self.true_obstacles)

    def _apply_obstacles_to_map_locked(self, obstacles: set[tuple[int, int]]) -> int:
        changed = 0
        changed_cells: list[dict[str, Any]] = []
        timestamp = now_ms()
        for cell in self.map["cells"]:
            point = (int(cell["x"]), int(cell["y"]))
            next_state = "OBSTACLE" if point in obstacles else "UNKNOWN"
            next_confidence = 1.0 if next_state == "OBSTACLE" else 0.0
            if (
                cell.get("state") == next_state
                and float(cell.get("confidence", 0.0)) == next_confidence
            ):
                continue
            cell.update(
                {
                    "state": next_state,
                    "confidence": next_confidence,
                    "updatedBy": "controller",
                    "updatedAt": timestamp,
                }
            )
            changed += 1
            changed_cells.append(copy.deepcopy(cell))

        if changed:
            previous_version = int(self.map["version"])
            self.map["version"] += 1
            self.map["updatedAt"] = timestamp
            self._rebuild_map_chunks_locked()
            self._record_map_delta_locked(previous_version, changed_cells)
        return changed

    def next_id(self, prefix: str) -> str:
        self._repair_counter_for_prefix(prefix)
        self._counters[prefix] += 1
        return f"{prefix}-{self._counters[prefix]:04d}"

    def _repair_counter_for_prefix(self, prefix: str) -> None:
        self._counters.setdefault(prefix, 0)
        self._counters[prefix] = max(
            int(self._counters.get(prefix, 0)),
            self._max_existing_counter_value(prefix),
        )

    def _max_existing_counter_value(self, prefix: str) -> int:
        values = [
            self._counter_value_from_id(prefix, candidate)
            for candidate in self._counter_id_candidates(prefix)
        ]
        return max(values, default=0)

    def _counter_id_candidates(self, prefix: str):
        if prefix == "event":
            for event in self.events:
                yield event.get("eventId")
        elif prefix == "task":
            yield from self.tasks.keys()
            for task in self.tasks.values():
                yield task.get("taskId")
        elif prefix == "frontier":
            yield from self.frontiers.keys()
            for frontier in self.frontiers.values():
                yield frontier.get("frontierId")
        elif prefix == "request":
            yield from self.navigation_requests.keys()
            for request in self.navigation_requests.values():
                yield request.get("requestId")
        elif prefix == "plan":
            yield from self.navigation_plans.keys()
            for plan in self.navigation_plans.values():
                yield plan.get("planId")

    @staticmethod
    def _counter_value_from_id(prefix: str, value: Any) -> int:
        if not isinstance(value, str):
            return 0
        marker = f"{prefix}-"
        if not value.startswith(marker):
            return 0
        try:
            return int(value[len(marker):])
        except ValueError:
            return 0

    def add_event(self, source: str, event_type: str, message: str) -> dict[str, Any]:
        event = {
            "eventId": self.next_id("event"),
            "source": source,
            "type": event_type,
            "message": message,
            "createdAt": now_ms(),
        }
        self.events.append(event)
        self.events = self.events[-120:]
        return event

    def prune_runtime_history_locked(self) -> None:
        active_statuses = {"PENDING", "PLANNED", "RUNNING"}
        active_task_ids = {
            task_id
            for task_id, task in self.tasks.items()
            if task.get("status") in active_statuses
        }
        recent_done_task_ids = {
            task_id
            for task_id, _ in sorted(
                (
                    (task_id, task)
                    for task_id, task in self.tasks.items()
                    if task_id not in active_task_ids
                ),
                key=lambda item: int(item[1].get("updatedAt", item[1].get("createdAt", 0))),
                reverse=True,
            )[:COMPLETED_TASK_HISTORY_LIMIT]
        }
        keep_task_ids = active_task_ids | recent_done_task_ids
        if len(keep_task_ids) < len(self.tasks):
            self.tasks = {
                task_id: task
                for task_id, task in self.tasks.items()
                if task_id in keep_task_ids
            }

        if len(self.frontiers) > INACTIVE_FRONTIER_HISTORY_LIMIT:
            active_frontiers = {
                frontier_id: frontier
                for frontier_id, frontier in self.frontiers.items()
                if frontier.get("status") in {"OPEN", "ASSIGNED"}
            }
            inactive_frontiers = sorted(
                (
                    (frontier_id, frontier)
                    for frontier_id, frontier in self.frontiers.items()
                    if frontier_id not in active_frontiers
                ),
                key=lambda item: int(item[1].get("updatedAt", item[1].get("timestamp", 0))),
                reverse=True,
            )[:INACTIVE_FRONTIER_HISTORY_LIMIT]
            self.frontiers = {
                **active_frontiers,
                **{frontier_id: frontier for frontier_id, frontier in inactive_frontiers},
            }

        active_request_statuses = {"PENDING", "PLANNING"}
        keep_request_ids = {
            request_id
            for request_id, request in self.navigation_requests.items()
            if request.get("status") in active_request_statuses
            or request.get("taskId") in keep_task_ids
        }
        keep_request_ids.update(
            request_id
            for request_id, _ in sorted(
                self.navigation_requests.items(),
                key=lambda item: int(item[1].get("updatedAt", item[1].get("createdAt", 0))),
                reverse=True,
            )[:NAVIGATION_HISTORY_LIMIT]
        )
        if len(keep_request_ids) < len(self.navigation_requests):
            self.navigation_requests = {
                request_id: request
                for request_id, request in self.navigation_requests.items()
                if request_id in keep_request_ids
            }

        keep_plan_ids = {
            plan_id
            for plan_id, plan in self.navigation_plans.items()
            if plan.get("taskId") in keep_task_ids
        }
        keep_plan_ids.update(
            plan_id
            for plan_id, _ in sorted(
                self.navigation_plans.items(),
                key=lambda item: int(item[1].get("createdAt", 0)),
                reverse=True,
            )[:NAVIGATION_HISTORY_LIMIT]
        )
        if len(keep_plan_ids) < len(self.navigation_plans):
            self.navigation_plans = {
                plan_id: plan
                for plan_id, plan in self.navigation_plans.items()
                if plan_id in keep_plan_ids
            }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return self._snapshot_payload_locked(self.map)

    def snapshot_view(self) -> dict[str, Any]:
        """Return the current in-process state without a deep copy.

        Component schedulers call this while holding ``batch()`` so algorithms
        can share one 50x50 map view instead of cloning it repeatedly.
        """
        snapshot_map = {
            key: value
            for key, value in self.map.items()
            if key != "chunks"
        }
        return {
            "map": snapshot_map,
            "vehicles": list(self.vehicles.values()),
            "frontiers": list(self.frontiers.values()),
            "tasks": list(self.tasks.values()),
            "navigationRequests": list(self.navigation_requests.values()),
            "navigationPlans": list(self.navigation_plans.values()),
            "heartbeats": list(self.heartbeats.values()),
            "events": self.events,
            "systemStatus": self.system_status,
            "snapshotAt": now_ms(),
        }

    def _snapshot_payload_locked(self, map_data: dict[str, Any]) -> dict[str, Any]:
        snapshot_map = {
            key: value
            for key, value in map_data.items()
            if key != "chunks"
        }
        return copy.deepcopy(
            {
                "map": snapshot_map,
                "vehicles": list(self.vehicles.values()),
                "frontiers": list(self.frontiers.values()),
                "tasks": list(self.tasks.values()),
                "navigationRequests": list(self.navigation_requests.values()),
                "navigationPlans": list(self.navigation_plans.values()),
                "heartbeats": list(self.heartbeats.values()),
                "events": list(self.events),
                "systemStatus": self.system_status,
                "snapshotAt": now_ms(),
            }
        )

    def snapshot_since(
        self,
        map_version: int | None = None,
        map_generation: int | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            if map_version is None:
                return self._snapshot_payload_locked(self.map)
            delta = self._map_delta_since_locked(int(map_version), map_generation)
            if delta is None:
                return self._snapshot_payload_locked(self.map)
            snapshot = self._snapshot_payload_locked(self._map_metadata(self.map))
            snapshot["mapDelta"] = delta
            return snapshot

    def set_system_status(self, status: str) -> dict[str, Any]:
        with self.lock:
            if status == "RESET":
                self.reset()
                return {"systemStatus": self.system_status}
            self.system_status = status
            self.add_event("controller", "SYSTEM_CONTROL", f"System status changed to {status}")
            return {"systemStatus": status}

    def register_vehicle(self, vehicle_id: str, pose: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            state = {
                "vehicleId": vehicle_id,
                "pose": pose,
                "speed": 1.0,
                "battery": 100,
                "status": "IDLE",
                "currentTaskId": None,
                "currentPlanId": None,
                "currentStepIndex": 0,
                "updatedAt": now_ms(),
            }
            self.vehicles[vehicle_id] = state
            self.update_heartbeat(vehicle_id, "ROBOT", "READY", None)
            self.add_event(vehicle_id, "VEHICLE_ONLINE", f"{vehicle_id} registered")
            return copy.deepcopy(state)

    def update_vehicle_state(self, data: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            vehicle_id = data["vehicleId"]
            current = self.vehicles.get(vehicle_id, {})
            current.update(data)
            current["updatedAt"] = data.get("updatedAt", now_ms())
            self.vehicles[vehicle_id] = current
            status = "BUSY" if current.get("status") in {"MOVING", "SCANNING"} else "READY"
            self.update_heartbeat(vehicle_id, "ROBOT", status, current.get("currentTaskId"))
            return copy.deepcopy(current)

    def update_heartbeat(
        self,
        component_id: str,
        component_type: str,
        status: str,
        current_work_id: str | None,
        host: str | None = None,
        pid: int | None = None,
    ) -> dict[str, Any]:
        heartbeat = {
            "componentId": component_id,
            "componentType": component_type,
            "status": status,
            "currentWorkId": current_work_id,
            "updatedAt": now_ms(),
        }
        if host:
            heartbeat["host"] = host
        if pid is not None:
            heartbeat["pid"] = pid
        self.heartbeats[component_id] = heartbeat
        return heartbeat

    def cell_at(self, x: int, y: int) -> dict[str, Any] | None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        return self.map["cells"][y * self.width + x]

    def upload_map_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            changed = 0
            changed_cells: list[dict[str, Any]] = []
            for incoming in patch.get("cells", []):
                x = int(incoming["x"])
                y = int(incoming["y"])
                cell = self.cell_at(x, y)
                if cell is None:
                    continue
                incoming_state = incoming["state"]
                incoming_confidence = incoming.get("confidence", 1.0)
                if (
                    cell.get("state") == incoming_state
                    and float(cell.get("confidence", 0.0)) == float(incoming_confidence)
                ):
                    continue
                cell.update(
                    {
                        "state": incoming_state,
                        "confidence": incoming_confidence,
                        "updatedBy": patch.get("vehicleId", incoming.get("updatedBy", "robot")),
                        "updatedAt": incoming.get("updatedAt", now_ms()),
                    }
                )
                changed += 1
                changed_cells.append(copy.deepcopy(cell))
            if changed:
                previous_version = int(self.map["version"])
                self.map["version"] += 1
                self.map["updatedAt"] = now_ms()
                self._record_map_delta_locked(previous_version, changed_cells)
                closed = self.refresh_frontiers_locked()
                self.add_event(
                    patch.get("vehicleId", "robot"),
                    "MAP_UPDATED",
                    f"Map patch merged: {changed} cells, version {self.map['version']}",
                )
                if closed:
                    self.add_event("controller", "FRONTIERS_CLOSED", f"{closed} stale frontiers closed")
            return {"mapVersion": self.map["version"], "changed": changed}

    def save_frontier(self, frontier: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            x = int(frontier["position"]["x"])
            y = int(frontier["position"]["y"])
            if not self._point_in_bounds((x, y)):
                raise ValueError(f"frontier position ({x}, {y}) is outside the map")
            for existing in self.frontiers.values():
                if existing["position"] == {"x": x, "y": y} and existing["status"] in {"OPEN", "ASSIGNED"}:
                    incoming_gain = int(frontier.get("unknownGain") or 0)
                    if incoming_gain > int(existing.get("unknownGain") or 0):
                        existing["unknownGain"] = incoming_gain
                    return copy.deepcopy(existing)

            frontier_id = frontier.get("frontierId") or self.next_id("frontier")
            saved = {
                "frontierId": frontier_id,
                "position": {"x": x, "y": y},
                "unknownGain": frontier.get("unknownGain", 0),
                "discoveredBy": frontier.get("discoveredBy", "robot"),
                "status": frontier.get("status", "OPEN"),
                "timestamp": frontier.get("timestamp", now_ms()),
            }
            self.frontiers[frontier_id] = saved
            self.add_event(saved["discoveredBy"], "FRONTIER_FOUND", f"Frontier found at ({x}, {y})")
            self.prune_runtime_history_locked()
            return copy.deepcopy(saved)

    def refresh_frontiers_locked(self, scan_radius: int = 2) -> int:
        cell_map = {
            (int(cell["x"]), int(cell["y"])): cell
            for cell in self.map["cells"]
        }
        closed = 0
        for frontier in self.frontiers.values():
            if frontier.get("status") not in {"OPEN", "ASSIGNED"}:
                continue
            position = frontier.get("position", {})
            point = (int(position.get("x", 0)), int(position.get("y", 0)))
            if not self._point_in_bounds(point):
                self._deactivate_frontier_locked(frontier, "CLOSED")
                closed += 1
                continue
            cell_state = cell_map.get(point, {}).get("state", "UNKNOWN")
            has_unknown_neighbor = self._has_unknown_neighbor(point, cell_map)
            unknown_gain = self._visible_unknown_gain(point, cell_map, scan_radius)
            if (
                cell_state not in {"FREE", "VISITED"}
                or not has_unknown_neighbor
                or unknown_gain <= 0
            ):
                next_status = "VISITED" if cell_state == "VISITED" else "CLOSED"
                self._deactivate_frontier_locked(frontier, next_status)
                closed += 1
                continue
            frontier["unknownGain"] = unknown_gain
        if closed:
            self.prune_runtime_history_locked()
        return closed

    def _has_unknown_neighbor(
        self,
        position: tuple[int, int],
        cell_map: dict[tuple[int, int], dict[str, Any]],
    ) -> bool:
        px, py = position
        return any(
            cell_map.get((x, y), {}).get("state") == "UNKNOWN"
            for x in range(px - 1, px + 2)
            for y in range(py - 1, py + 2)
            if (x, y) != (px, py)
        )

    def _visible_unknown_gain(
        self,
        position: tuple[int, int],
        cell_map: dict[tuple[int, int], dict[str, Any]],
        scan_radius: int,
    ) -> int:
        return sum(
            1
            for point in visible_points_in_square(
                position,
                scan_radius,
                in_bounds=lambda candidate: candidate in cell_map,
                is_blocked=lambda candidate: (
                    cell_map.get(candidate, {}).get("state") == "OBSTACLE"
                ),
            )
            if cell_map.get(point, {}).get("state") == "UNKNOWN"
        )

    def _deactivate_frontier_locked(
        self,
        frontier: dict[str, Any],
        status: str,
    ) -> None:
        frontier["status"] = status
        frontier["unknownGain"] = 0
        frontier["updatedAt"] = now_ms()
        frontier_id = frontier.get("frontierId")
        for task in self.tasks.values():
            if (
                task.get("frontierId") != frontier_id
                or task.get("status") != "PENDING"
            ):
                continue
            task["status"] = "CANCELLED"
            task["updatedAt"] = now_ms()
            vehicle = self.vehicles.get(task.get("vehicleId"))
            if vehicle and vehicle.get("currentTaskId") == task.get("taskId"):
                vehicle["status"] = "IDLE"
                vehicle["currentTaskId"] = None
                vehicle["currentPlanId"] = None
                vehicle["currentStepIndex"] = 0
            for request in self.navigation_requests.values():
                if (
                    request.get("taskId") == task.get("taskId")
                    and request.get("status") in {"PENDING", "PLANNING"}
                ):
                    request["status"] = "CANCELLED"
                    request["updatedAt"] = now_ms()

    def create_task_for_frontier(self, vehicle_id: str, frontier: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            task_id = self.next_id("task")
            task = {
                "taskId": task_id,
                "vehicleId": vehicle_id,
                "target": frontier["position"],
                "frontierId": frontier["frontierId"],
                "status": "PENDING",
                "planId": None,
                "pathQueue": [],
                "currentStepIndex": 0,
                "replanCount": 0,
                "createdAt": now_ms(),
                "updatedAt": now_ms(),
            }
            self.tasks[task_id] = task
            self.frontiers[frontier["frontierId"]]["status"] = "ASSIGNED"
            self.vehicles[vehicle_id]["currentTaskId"] = task_id
            self.add_event("controller", "TASK_ASSIGNED", f"{task_id} assigned to {vehicle_id}")
            return copy.deepcopy(task)

    def create_navigation_request(self, task: dict[str, Any], priority: int = 5) -> dict[str, Any]:
        with self.lock:
            vehicle = self.vehicles.get(task["vehicleId"])
            if not vehicle:
                raise ValueError("vehicle not found")
            request_id = self.next_id("request")
            request = {
                "requestId": request_id,
                "vehicleId": task["vehicleId"],
                "taskId": task["taskId"],
                "start": copy.deepcopy(vehicle["pose"]["position"]),
                "goal": copy.deepcopy(task["target"]),
                "mapVersion": self.map["version"],
                "priority": priority,
                "avoidVehicles": True,
                "status": "PENDING",
                "assignedNavigatorId": None,
                "createdAt": now_ms(),
                "updatedAt": now_ms(),
            }
            self.navigation_requests[request_id] = request
            return copy.deepcopy(request)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.lock:
            task = self.tasks.get(task_id)
            return copy.deepcopy(task) if task else None

    def save_navigation_request(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            request_id = request.get("requestId") or self.next_id("request")
            saved = copy.deepcopy(request)
            saved["requestId"] = request_id
            saved["status"] = saved.get("status", "PENDING")
            saved["createdAt"] = saved.get("createdAt", now_ms())
            saved["updatedAt"] = saved.get("updatedAt", now_ms())
            self.navigation_requests[request_id] = saved
            return copy.deepcopy(saved)

    def has_active_request_for_task(self, task_id: str) -> bool:
        return any(
            request["taskId"] == task_id and request["status"] in {"PENDING", "PLANNING"}
            for request in self.navigation_requests.values()
        )

    def claim_navigation_request(self, navigator_id: str) -> dict[str, Any]:
        with self.lock:
            pending = [
                request
                for request in self.navigation_requests.values()
                if request["status"] == "PENDING"
            ]
            if not pending:
                self.update_heartbeat(navigator_id, "NAVIGATOR", "READY", None)
                return {"claimed": False, "requestId": None}
            pending.sort(key=lambda item: (-int(item["priority"]), int(item["createdAt"])))
            request = pending[0]
            request["status"] = "PLANNING"
            request["assignedNavigatorId"] = navigator_id
            request["updatedAt"] = now_ms()
            self.update_heartbeat(navigator_id, "NAVIGATOR", "BUSY", request["requestId"])
            return {"claimed": True, "requestId": request["requestId"], "request": copy.deepcopy(request)}

    def claim_navigation_requests(self, navigator_id: str, limit: int | None = None) -> dict[str, Any]:
        with self.lock:
            pending = [
                request
                for request in self.navigation_requests.values()
                if request["status"] == "PENDING"
            ]
            if not pending:
                self.update_heartbeat(navigator_id, "NAVIGATOR", "READY", None)
                return {"claimed": False, "requests": []}

            pending.sort(key=lambda item: (-int(item["priority"]), int(item["createdAt"])))
            selected = pending if limit is None else pending[:limit]
            for request in selected:
                request["status"] = "PLANNING"
                request["assignedNavigatorId"] = navigator_id
                request["updatedAt"] = now_ms()
            active_request = selected[0]["requestId"] if len(selected) == 1 else f"CBS_BATCH:{len(selected)}"
            self.update_heartbeat(navigator_id, "NAVIGATOR", "BUSY", active_request)
            return {"claimed": True, "requests": copy.deepcopy(selected)}

    def write_navigation_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            plan_id = plan.get("planId") or self.next_id("plan")
            plan["planId"] = plan_id
            plan["createdAt"] = plan.get("createdAt", now_ms())
            self.navigation_plans[plan_id] = copy.deepcopy(plan)

            request = self.navigation_requests.get(plan["requestId"])
            task = self.tasks.get(plan["taskId"])
            if task and task.get("status") == "CANCELLED":
                if request:
                    request["status"] = "CANCELLED"
                    request["updatedAt"] = now_ms()
                self.update_heartbeat(plan.get("createdBy", "navigator"), "NAVIGATOR", "READY", None)
                return copy.deepcopy(plan)
            if request:
                request["status"] = "SUCCESS" if plan["status"] == "SUCCESS" else "FAILED"
                request["updatedAt"] = now_ms()
            if task:
                if plan["status"] == "SUCCESS":
                    task["status"] = "PLANNED"
                    task["planId"] = plan_id
                    task["pathQueue"] = copy.deepcopy(plan.get("path", []))
                    task["currentStepIndex"] = 0
                    self.add_event(plan["createdBy"], "PLAN_SUCCESS", f"{plan_id} created for {task['taskId']}")
                else:
                    task["status"] = "FAILED"
                    frontier = self.frontiers.get(task.get("frontierId"))
                    if frontier:
                        self._deactivate_frontier_locked(frontier, "CLOSED")
                    vehicle = self.vehicles.get(task.get("vehicleId"))
                    if vehicle and vehicle.get("currentTaskId") == task.get("taskId"):
                        vehicle["status"] = "IDLE"
                        vehicle["currentTaskId"] = None
                        vehicle["currentPlanId"] = None
                        vehicle["currentStepIndex"] = 0
                    self.add_event(plan["createdBy"], "PLAN_FAILED", plan.get("failReason", "planning failed"))
                task["updatedAt"] = now_ms()
            self.prune_runtime_history_locked()
            self.update_heartbeat(plan.get("createdBy", "navigator"), "NAVIGATOR", "READY", None)
            return copy.deepcopy(plan)

    def get_vehicle_task(self, vehicle_id: str) -> dict[str, Any] | None:
        with self.lock:
            for task in self.tasks.values():
                if task["vehicleId"] == vehicle_id and task["status"] not in {"DONE", "FAILED", "CANCELLED"}:
                    return copy.deepcopy(task)
            return None

    def mark_task_running(self, task_id: str) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            if task and task["status"] in {"PLANNED", "PENDING"}:
                task["status"] = "RUNNING"
                task["updatedAt"] = now_ms()

    def mark_task_progress(self, task_id: str, step_index: int) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            if task:
                task["currentStepIndex"] = step_index
                task["updatedAt"] = now_ms()

    def mark_task_done(self, task_id: str) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            task["status"] = "DONE"
            task["updatedAt"] = now_ms()
            if task.get("frontierId") in self.frontiers:
                self.frontiers[task["frontierId"]]["status"] = "VISITED"
            vehicle = self.vehicles.get(task["vehicleId"])
            if vehicle:
                vehicle["status"] = "IDLE"
                vehicle["currentTaskId"] = None
                vehicle["currentPlanId"] = None
                vehicle["currentStepIndex"] = 0
            self.add_event(task["vehicleId"], "TASK_DONE", f"{task_id} completed")
            self.prune_runtime_history_locked()

    def report_blocked(self, vehicle_id: str, task_id: str, blocked_at: dict[str, int]) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            vehicle = self.vehicles.get(vehicle_id)
            if task:
                task["status"] = "PENDING"
                task["pathQueue"] = []
                task["planId"] = None
                task["currentStepIndex"] = 0
                task["replanCount"] = task.get("replanCount", 0) + 1
                task["updatedAt"] = now_ms()
            if vehicle:
                vehicle["status"] = "BLOCKED"
                vehicle["updatedAt"] = now_ms()
            self.add_event(
                vehicle_id,
                "VEHICLE_BLOCKED",
                f"{vehicle_id} blocked at ({blocked_at['x']}, {blocked_at['y']}), replan requested",
            )
            self.prune_runtime_history_locked()

    def active_task_vehicle_ids(self) -> set[str]:
        return {
            task["vehicleId"]
            for task in self.tasks.values()
            if task["status"] not in {"DONE", "FAILED", "CANCELLED"}
        }

    def open_frontiers(self) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(item)
            for item in self.frontiers.values()
            if item["status"] == "OPEN"
            and self._point_in_bounds(
                (
                    int(item.get("position", {}).get("x", -1)),
                    int(item.get("position", {}).get("y", -1)),
                )
            )
        ]

    def idle_vehicles(self) -> list[dict[str, Any]]:
        active = self.active_task_vehicle_ids()
        return [
            copy.deepcopy(vehicle)
            for vehicle in self.vehicles.values()
            if vehicle["status"] in {"IDLE", "SCANNING"} and vehicle["vehicleId"] not in active
        ]

    def pending_tasks_without_request(self) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(task)
            for task in self.tasks.values()
            if task["status"] == "PENDING" and not self.has_active_request_for_task(task["taskId"])
        ]

    def is_truth_blocked(self, point: dict[str, int]) -> bool:
        return (int(point["x"]), int(point["y"])) in self.true_obstacles
