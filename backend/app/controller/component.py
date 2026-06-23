from __future__ import annotations

from typing import Any

from ..redis import Blackboard
from .policies import AssignmentPolicy


class ControllerComponent:
    """Controller component: assign exploration targets and create navigation requests."""

    def __init__(
        self,
        blackboard: Blackboard,
        assignment_policy: AssignmentPolicy,
        scan_radius: int,
        component_id: str = "controller-01",
    ) -> None:
        self.blackboard = blackboard
        self.assignment_policy = assignment_policy
        self.scan_radius = scan_radius
        self.component_id = component_id

    def run_once(self) -> None:
        self.blackboard.update_heartbeat(self.component_id, "CONTROLLER", "BUSY", "assignment")
        self.blackboard.refresh_frontiers_locked(self.scan_radius)

        for task in self.blackboard.pending_tasks_without_request():
            try:
                self.blackboard.create_navigation_request(task, priority=8 if task.get("replanCount") else 5)
            except ValueError:
                continue

        snapshot = self.blackboard.snapshot_view()
        frontiers = self.blackboard.open_frontiers()
        if not frontiers:
            self.blackboard.update_heartbeat(self.component_id, "CONTROLLER", "READY", None)
            return

        frontier_by_id = {frontier["frontierId"]: frontier for frontier in frontiers}
        idle_vehicles = self.blackboard.idle_vehicles()
        assigned_frontiers: set[str] = set()
        assigned_vehicles: set[str] = set()
        decisions = self.assignment_policy.select_assignments(
            snapshot,
            idle_vehicles,
            frontiers,
            scan_radius=self.scan_radius,
        )

        for decision in decisions:
            if decision.vehicle_id in assigned_vehicles or decision.frontier_id in assigned_frontiers:
                continue
            vehicle = next(
                (item for item in idle_vehicles if item["vehicleId"] == decision.vehicle_id),
                None,
            )
            best = frontier_by_id.get(decision.frontier_id)
            if not vehicle or not best:
                continue

            task = self.blackboard.create_task_for_frontier(vehicle["vehicleId"], best)
            self.blackboard.create_navigation_request(task, priority=decision.priority)
            assigned_vehicles.add(decision.vehicle_id)
            assigned_frontiers.add(decision.frontier_id)

        self.blackboard.update_heartbeat(self.component_id, "CONTROLLER", "READY", None)

    def choose_frontier(self, vehicle: dict[str, Any], frontiers: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not frontiers:
            return None
        snapshot = self.blackboard.snapshot()
        cell_map = {(cell["x"], cell["y"]): cell for cell in snapshot["map"]["cells"]}
        chooser = getattr(self.assignment_policy, "choose_frontier", None)
        if chooser is None:
            return None
        selected = chooser(vehicle, frontiers, cell_map, self.scan_radius)
        if selected is None:
            return None
        return selected["frontier"]
