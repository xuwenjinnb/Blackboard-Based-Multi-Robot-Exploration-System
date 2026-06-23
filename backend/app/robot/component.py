from __future__ import annotations

from .algorithms.factory import create_frontier_scan_algorithm, create_low_level_mdp_algorithm
from ..redis import Blackboard, now_ms
from ..config import SimulationConfig
from ..pathfinding import heading_between


class RobotComponent:
    """Simulated robot/car component: execute paths, scan, and upload map data."""

    def __init__(self, blackboard: Blackboard, config: SimulationConfig) -> None:
        self.blackboard = blackboard
        self._config = config
        self._configure_algorithms()

    @property
    def config(self) -> SimulationConfig:
        return self._config

    @config.setter
    def config(self, value: SimulationConfig) -> None:
        self._config = value
        self._configure_algorithms()

    def _configure_algorithms(self) -> None:
        self.frontier_scan = create_frontier_scan_algorithm(self.blackboard, self._config)
        self.low_level_mdp = create_low_level_mdp_algorithm(self.blackboard, self._config, self.frontier_scan)

    @property
    def scan_radius(self) -> int:
        return self.config.scan_radius

    @property
    def frontier_search_radius(self) -> int:
        return self.config.frontier_search_radius

    @property
    def uses_low_level_mdp(self) -> bool:
        return self.low_level_mdp.enabled

    def run_once(self) -> int:
        moves = 0
        snapshot = self.blackboard.snapshot_view()
        for vehicle in snapshot["vehicles"]:
            moves += self.run_vehicle_once(vehicle["vehicleId"], vehicle=vehicle)
        return moves

    def run_vehicle_once(self, vehicle_id: str, *, vehicle: dict | None = None) -> int:
        if vehicle is None:
            snapshot = self.blackboard.snapshot_view()
            vehicle = next((item for item in snapshot["vehicles"] if item["vehicleId"] == vehicle_id), None)
        if not vehicle:
            return 0

        task = self.blackboard.get_vehicle_task(vehicle_id)
        if not task:
            self.blackboard.update_vehicle_state({**vehicle, "status": "SCANNING"})
            self.scan_and_upload(vehicle_id)
            self.blackboard.update_vehicle_state({**vehicle, "status": "IDLE"})
            return 0

        if task["status"] in {"PENDING", "FAILED"}:
            self.scan_and_upload(vehicle_id)
            return 0

        path = task.get("pathQueue", [])
        if not path:
            return 0

        self.blackboard.mark_task_running(task["taskId"])
        current_index = int(task.get("currentStepIndex", 0))
        next_index = current_index + 1
        if next_index >= len(path):
            self.blackboard.mark_task_done(task["taskId"])
            return 0

        next_step = path[next_index]
        next_position = next_step["position"]
        current_position = vehicle["pose"]["position"]
        if self.blackboard.is_truth_blocked(next_position):
            self.scan_and_upload(vehicle_id)
            self.blackboard.report_blocked(vehicle_id, task["taskId"], next_position)
            return 0

        updated = {
            **vehicle,
            "pose": {"position": next_position, "heading": next_step.get("heading", 0)},
            "status": "MOVING",
            "currentTaskId": task["taskId"],
            "currentPlanId": task.get("planId"),
            "currentStepIndex": next_index,
            "battery": max(0, int(vehicle.get("battery", 100)) - 1),
            "updatedAt": now_ms(),
        }
        self.blackboard.update_vehicle_state(updated)
        self.blackboard.mark_task_progress(task["taskId"], next_index)
        self.scan_and_upload(vehicle_id)
        return 1 if next_position != current_position else 0

    def run_low_level_mdp_once(self) -> int:
        return self.low_level_mdp.run_once()

    def run_low_level_mdp_vehicle_once(self, vehicle_id: str) -> int:
        snapshot = self.blackboard.snapshot_view()
        vehicle = next((item for item in snapshot["vehicles"] if item["vehicleId"] == vehicle_id), None)
        if vehicle is None:
            return 0

        current = point_tuple(vehicle["pose"]["position"])
        next_cell = self.low_level_mdp.choose_step(
            vehicle,
            snapshot,
            selected_next=set(),
            selected_edges=set(),
        )
        if next_cell is None:
            next_cell = current

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
        self.scan_and_upload(vehicle_id)
        self.blackboard.update_vehicle_state({**updated, "status": "IDLE"})
        return 1 if next_cell != current else 0

    def scan_and_upload(self, vehicle_id: str, *, detect_frontiers: bool | None = None) -> None:
        self.frontier_scan.scan_and_upload(vehicle_id, detect_frontiers=detect_frontiers)

    def detect_frontiers(self, vehicle_id: str, center: dict[str, int], radius: int) -> None:
        self.frontier_scan.detect_frontiers(vehicle_id, center, radius)

    def unknown_cells_visible_from(self, position, cell_map) -> int:
        return self.frontier_scan.unknown_cells_visible_from(position, cell_map)

    def choose_low_level_mdp_step(self, vehicle, snapshot, *, selected_next, selected_edges):
        return self.low_level_mdp.choose_step(
            vehicle,
            snapshot,
            selected_next=selected_next,
            selected_edges=selected_edges,
        )


def point_tuple(point: dict[str, int]) -> tuple[int, int]:
    return int(point["x"]), int(point["y"])
