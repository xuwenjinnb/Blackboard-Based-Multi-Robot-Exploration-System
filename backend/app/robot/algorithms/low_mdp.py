from __future__ import annotations

from typing import Any

from .frontier_scan import FrontierScanAlgorithm, neighbors4, neighbors4_with_wait, point_tuple
from ...redis import Blackboard, now_ms
from ...config import SimulationConfig
from ...pathfinding import heading_between
from ...controller.policies.helpers import unknown_cells_visible_from


class LowLevelMDPAlgorithm:
    """Low-level MDP movement policy for direct robot exploration."""

    policy_names = {"low_mdp", "low-mdp", "low-level-mdp", "low_level_mdp"}

    def __init__(self, blackboard: Blackboard, config: SimulationConfig, scanner: FrontierScanAlgorithm) -> None:
        self.blackboard = blackboard
        self.config = config
        self.scanner = scanner

    @property
    def enabled(self) -> bool:
        return self.config.policy.strip().lower() in self.policy_names

    def run_once(self) -> int:
        moves = 0
        selected_next: dict[str, tuple[int, int]] = {}
        selected_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()

        for vehicle_id in [vehicle["vehicleId"] for vehicle in self.blackboard.snapshot_view()["vehicles"]]:
            snapshot = self.blackboard.snapshot_view()
            vehicle = next(
                (item for item in snapshot["vehicles"] if item["vehicleId"] == vehicle_id),
                None,
            )
            if vehicle is None:
                continue
            vehicle_id = vehicle["vehicleId"]
            current = point_tuple(vehicle["pose"]["position"])
            next_cell = self.choose_step(
                vehicle,
                snapshot,
                selected_next=set(selected_next.values()),
                selected_edges=selected_edges,
            )
            if next_cell is None:
                next_cell = current

            selected_next[vehicle_id] = next_cell
            selected_edges.add((current, next_cell))

            heading = heading_between(current, next_cell)
            position = {"x": next_cell[0], "y": next_cell[1]}
            status = "SCANNING" if next_cell == current else "MOVING"
            updated = {
                **vehicle,
                "pose": {"position": position, "heading": heading},
                "status": status,
                "currentTaskId": None,
                "currentPlanId": None,
                "currentStepIndex": 0,
                "battery": max(0, int(vehicle.get("battery", 100)) - (0 if next_cell == current else 1)),
                "updatedAt": now_ms(),
            }
            self.blackboard.update_vehicle_state(updated)
            if next_cell != current:
                moves += 1
            self.scanner.scan_and_upload(vehicle_id)

        for vehicle in self.blackboard.snapshot_view()["vehicles"]:
            self.blackboard.update_vehicle_state({**vehicle, "status": "IDLE"})
        return moves

    def choose_step(
        self,
        vehicle: dict[str, Any],
        snapshot: dict[str, Any],
        *,
        selected_next: set[tuple[int, int]],
        selected_edges: set[tuple[tuple[int, int], tuple[int, int]]],
    ) -> tuple[int, int] | None:
        start = point_tuple(vehicle["pose"]["position"])
        states = local_known_traversable_cells(
            snapshot["map"],
            start,
            self.config.low_level_mdp_horizon,
        )
        if not states:
            return start

        cell_map = {(int(cell["x"]), int(cell["y"])): cell for cell in snapshot["map"]["cells"]}
        rewards = {
            state: float(
                unknown_cells_visible_from(
                    {"x": state[0], "y": state[1]},
                    cell_map,
                    self.config.scan_radius,
                )
            )
            for state in states
        }
        repulsion = self.repulsion_field(snapshot, states, start, selected_next)
        values = {
            state: rewards.get(state, 0.0) - repulsion.get(state, 0.0)
            for state in states
        }
        discount = self.config.low_level_mdp_discount

        for _ in range(self.config.low_level_mdp_iterations):
            biggest_change = 0.0
            next_values: dict[tuple[int, int], float] = {}
            for state in states:
                neighbor_values = [
                    values[neighbor] - self.config.low_level_mdp_move_cost
                    for neighbor in neighbors4_with_wait(state)
                    if neighbor in states
                ]
                best_next = max(neighbor_values) if neighbor_values else values[state]
                updated = rewards.get(state, 0.0) - repulsion.get(state, 0.0) + discount * best_next
                next_values[state] = updated
                biggest_change = max(biggest_change, abs(updated - values[state]))
            values = next_values
            if biggest_change < 0.01:
                break

        candidates: list[tuple[float, int, int, tuple[int, int]]] = []
        for candidate in neighbors4_with_wait(start):
            if candidate not in states:
                continue
            if candidate != start and candidate in selected_next:
                continue
            if (candidate, start) in selected_edges:
                continue
            if self.blackboard.is_truth_blocked({"x": candidate[0], "y": candidate[1]}):
                continue

            move_penalty = 0.0 if candidate == start else self.config.low_level_mdp_move_cost
            score = (
                rewards.get(candidate, 0.0)
                - repulsion.get(candidate, 0.0)
                + discount * values.get(candidate, 0.0)
                - move_penalty
            )
            is_move = 1 if candidate != start else 0
            candidates.append((score, is_move, rewards.get(candidate, 0.0), candidate))

        if not candidates:
            return start
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        best = candidates[0]
        if best[0] <= 0.0 and best[2] <= 0.0:
            fallback = self.unknown_fallback_step(snapshot, start, selected_next, selected_edges)
            if fallback is not None:
                return fallback
        return best[3]

    def unknown_fallback_step(
        self,
        snapshot: dict[str, Any],
        start: tuple[int, int],
        selected_next: set[tuple[int, int]],
        selected_edges: set[tuple[tuple[int, int], tuple[int, int]]],
    ) -> tuple[int, int] | None:
        cell_map = {(int(cell["x"]), int(cell["y"])): cell for cell in snapshot["map"]["cells"]}
        width = int(snapshot["map"]["width"])
        height = int(snapshot["map"]["height"])
        queue: list[tuple[int, int]] = [start]
        parents: dict[tuple[int, int], tuple[int, int] | None] = {start: None}

        while queue:
            current = queue.pop(0)
            if current != start and unknown_cells_visible_from(
                {"x": current[0], "y": current[1]},
                cell_map,
                self.config.scan_radius,
            ) > 0:
                step = current
                while parents.get(step) is not None and parents[step] != start:
                    step = parents[step]  # type: ignore[assignment]
                if step != start and step not in selected_next and (step, start) not in selected_edges:
                    return step
                return None

            for neighbor in neighbors4(current):
                if neighbor in parents:
                    continue
                if not (0 <= neighbor[0] < width and 0 <= neighbor[1] < height):
                    continue
                if neighbor in selected_next:
                    continue
                cell = cell_map.get(neighbor)
                state = cell.get("state", "UNKNOWN") if cell else "UNKNOWN"
                if state not in {"FREE", "VISITED"}:
                    continue
                if self.blackboard.is_truth_blocked({"x": neighbor[0], "y": neighbor[1]}):
                    continue
                parents[neighbor] = current
                queue.append(neighbor)

        return None

    def repulsion_field(
        self,
        snapshot: dict[str, Any],
        states: set[tuple[int, int]],
        start: tuple[int, int],
        selected_next: set[tuple[int, int]],
    ) -> dict[tuple[int, int], float]:
        sources: list[tuple[tuple[int, int], float]] = []
        for vehicle in snapshot.get("vehicles", []):
            position = point_tuple(vehicle["pose"]["position"])
            if position != start:
                sources.append((position, self.config.low_level_mdp_repulsion_weight))
        for reserved in selected_next:
            sources.append((reserved, self.config.low_level_mdp_repulsion_weight * 2.0))

        field: dict[tuple[int, int], float] = {}
        for state in states:
            penalty = 0.0
            for source, weight in sources:
                distance = abs(state[0] - source[0]) + abs(state[1] - source[1])
                if distance <= self.config.low_level_mdp_horizon:
                    penalty += weight * (self.config.low_level_mdp_discount ** distance)
            field[state] = penalty
        return field


def local_known_traversable_cells(
    map_grid: dict[str, Any],
    start: tuple[int, int],
    horizon: int,
) -> set[tuple[int, int]]:
    width = int(map_grid["width"])
    height = int(map_grid["height"])
    cells = {(int(cell["x"]), int(cell["y"])): cell for cell in map_grid["cells"]}
    states: set[tuple[int, int]] = set()
    queue: list[tuple[tuple[int, int], int]] = [(start, 0)]

    while queue:
        current, distance = queue.pop(0)
        if current in states or distance > horizon:
            continue
        if not (0 <= current[0] < width and 0 <= current[1] < height):
            continue
        cell = cells.get(current)
        state = cell.get("state", "UNKNOWN") if cell else "UNKNOWN"
        if current != start and state not in {"FREE", "VISITED"}:
            continue
        states.add(current)
        for neighbor in neighbors4(current):
            if neighbor not in states:
                queue.append((neighbor, distance + 1))

    return states
