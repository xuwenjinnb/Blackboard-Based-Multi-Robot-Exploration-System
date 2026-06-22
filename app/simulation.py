from __future__ import annotations

import asyncio
import random
from dataclasses import replace
from typing import Any

from .blackboard import Blackboard
from .config import SimulationConfig
from .controller import ControllerComponent
from .navigator import NavigatorComponent
from .controller.policies import AssignmentPolicy, create_assignment_policy
from .robot import RobotComponent


class SimulationEngine:
    """Unified scheduler for the split Robot, Controller, and Navigator components."""

    def __init__(
        self,
        blackboard: Blackboard,
        assignment_policy: AssignmentPolicy | None = None,
        config: SimulationConfig | None = None,
    ) -> None:
        self.blackboard = blackboard
        self._config = config or SimulationConfig()
        self.assignment_policy = assignment_policy or create_assignment_policy(self._config.policy)
        self.running = False
        self._task: asyncio.Task[None] | None = None
        self.tick = 0
        self.movement_steps = 0
        self.navigator_ids = self._build_navigator_ids(self._config.navigator_count)
        self.vehicle_deployment = self._build_random_vehicle_deployment(self._default_vehicle_count())
        self.robot_component = RobotComponent(self.blackboard, self._config)
        self.controller_component = ControllerComponent(
            self.blackboard,
            self.assignment_policy,
            self._config.scan_radius,
        )
        self.navigator_component = NavigatorComponent(self.blackboard, self._config, self.navigator_ids)

    @property
    def config(self) -> SimulationConfig:
        return self._config

    @config.setter
    def config(self, value: SimulationConfig) -> None:
        self._config = value
        if hasattr(self, "robot_component"):
            self.robot_component.config = value
        if hasattr(self, "controller_component"):
            self.controller_component.scan_radius = value.scan_radius
        if hasattr(self, "navigator_component"):
            self.navigator_component.config = value
            self.navigator_ids = self._build_navigator_ids(value.navigator_count)
            self.navigator_component.navigator_ids = self.navigator_ids

    @property
    def scan_radius(self) -> int:
        return self.config.scan_radius

    @property
    def frontier_search_radius(self) -> int:
        return self.config.frontier_search_radius

    @property
    def uses_low_level_mdp(self) -> bool:
        return self.robot_component.uses_low_level_mdp

    def start_background(self) -> None:
        if self._task is None or self._task.done():
            self.running = True
            self._task = asyncio.create_task(self._loop())

    async def stop_background(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        self.ensure_demo_vehicles()
        while self.running:
            if self.blackboard.system_status == "RUNNING":
                await asyncio.to_thread(self.step)
            await asyncio.sleep(0.45)

    def ensure_demo_vehicles(self) -> None:
        snapshot = self.blackboard.snapshot()
        if snapshot["vehicles"]:
            return
        with self.blackboard.batch():
            snapshot = self.blackboard.snapshot()
            if snapshot["vehicles"]:
                return
            if self._deployment_intersects_obstacles():
                self.vehicle_deployment = self._build_random_vehicle_deployment(self._vehicle_deployment_count())
            for item in self.vehicle_deployment["vehicles"]:
                vehicle_id = item["vehicleId"]
                pose = {"position": {"x": item["x"], "y": item["y"]}, "heading": item["heading"]}
                self.blackboard.register_vehicle(vehicle_id, pose)
                self.scan_and_upload(vehicle_id)
            for navigator_id in self.navigator_ids:
                self.blackboard.update_heartbeat(navigator_id, "NAVIGATOR", "READY", None)
            self.blackboard.update_heartbeat("controller-01", "CONTROLLER", "READY", None)

    def configure_vehicle_deployment(
        self,
        *,
        count: int,
        mode: str = "manual",
        positions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self.blackboard.batch():
            normalized_mode = (mode or "random").strip().lower()
            if normalized_mode in {"manual", "custom"} and positions:
                self.vehicle_deployment = self._build_manual_vehicle_deployment(count, positions)
            else:
                self.vehicle_deployment = self._build_random_vehicle_deployment(count)
            self._reset_runtime_for_vehicle_deployment_locked()
            self.blackboard.add_event(
                "controller",
                "VEHICLES_CONFIGURED",
                f"{self.vehicle_deployment['count']} vehicles deployed by {self.vehicle_deployment['mode']} mode",
            )
            return self.vehicle_deployment

    def configure_navigator_count(self, count: int) -> dict[str, Any]:
        with self.blackboard.batch():
            previous_ids = set(self.navigator_ids)
            next_ids = self._build_navigator_ids(count)
            self.config = replace(self.config, navigator_count=len(next_ids))
            self.navigator_ids = next_ids
            self.navigator_component.navigator_ids = next_ids
            for navigator_id in next_ids:
                self.blackboard.update_heartbeat(navigator_id, "NAVIGATOR", "READY", None)
            for navigator_id in previous_ids - set(next_ids):
                self.blackboard.heartbeats.pop(navigator_id, None)
            self.blackboard.add_event(
                "navigator",
                "NAVIGATORS_CONFIGURED",
                f"{len(next_ids)} navigators configured",
            )
            return {"count": len(next_ids), "navigatorIds": next_ids}

    def configure_obstacles(
        self,
        *,
        mode: str,
        obstacles: list[dict[str, Any]] | None = None,
        density: float = 0.18,
        seed: int | None = None,
        count: int | None = None,
    ) -> dict[str, Any]:
        with self.blackboard.batch():
            result = self.blackboard.configure_obstacles(
                mode=mode,
                obstacles=obstacles,
                density=density,
                seed=seed,
                count=count,
            )
            self.vehicle_deployment = self._build_random_vehicle_deployment(self._vehicle_deployment_count())
            self._reset_runtime_for_vehicle_deployment_locked()
            return result

    def configure_map(self, *, width: int, height: int, chunk_size: int | None = None) -> dict[str, Any]:
        with self.blackboard.batch():
            result = self.blackboard.configure_map(width=width, height=height, chunk_size=chunk_size)
            self.vehicle_deployment = self._build_random_vehicle_deployment(self._vehicle_deployment_count())
            self._reset_runtime_for_vehicle_deployment_locked()
            return result

    def set_obstacle_at(self, x: int, y: int, blocked: bool | None = None) -> dict[str, Any]:
        with self.blackboard.batch():
            result = self.blackboard.set_obstacle_at(x, y, blocked)
            self._reset_runtime_for_vehicle_deployment_locked()
            return result

    def set_obstacles_at(self, cells: list[dict[str, Any]]) -> dict[str, Any]:
        with self.blackboard.batch():
            result = self.blackboard.set_obstacles_at(cells)
            if result.get("cells"):
                self._reset_runtime_for_vehicle_deployment_locked()
            return result

    def _reset_runtime_for_vehicle_deployment_locked(self) -> None:
        self.blackboard.clear_runtime_state_locked()
        self.blackboard.reset_perception_map_locked()
        self.tick = 0
        self.movement_steps = 0
        self.ensure_demo_vehicles()

    def step(self) -> None:
        with self.blackboard.batch():
            self._step()

    def _step(self) -> None:
        self.tick += 1
        self.ensure_demo_vehicles()
        if self.uses_low_level_mdp:
            self.movement_steps += self.low_level_mdp_phase()
            if self.exploration_complete():
                self.pause_completed_exploration()
            return
        self.movement_steps += self.robot_phase()
        self.controller_phase()
        self.navigator_phase()

    def robot_phase(self) -> int:
        return self.robot_component.run_once()

    def low_level_mdp_phase(self) -> int:
        return self.robot_component.run_low_level_mdp_once()

    def controller_phase(self) -> None:
        self.controller_component.assignment_policy = self.assignment_policy
        self.controller_component.scan_radius = self.scan_radius
        self.controller_component.run_once()

    def navigator_phase(self) -> None:
        self.navigator_component.config = self.config
        self.navigator_component.run_once()

    def exploration_complete(self) -> bool:
        snapshot = self.blackboard.snapshot()
        return all(cell.get("state") != "UNKNOWN" for cell in snapshot["map"]["cells"])

    def pause_completed_exploration(self) -> None:
        if self.blackboard.system_status == "RUNNING":
            self.blackboard.set_system_status("PAUSED")
            self.blackboard.add_event(
                "robot",
                "EXPLORATION_COMPLETE",
                "Low-level MDP paused because no UNKNOWN cells remain",
            )

    def scan_and_upload(self, vehicle_id: str, *, detect_frontiers: bool | None = None) -> None:
        self.robot_component.scan_and_upload(vehicle_id, detect_frontiers=detect_frontiers)

    def detect_frontiers(self, vehicle_id: str, center: dict[str, int], radius: int) -> None:
        self.robot_component.detect_frontiers(vehicle_id, center, radius)

    def unknown_cells_visible_from(
        self,
        position: dict[str, int],
        cell_map: dict[tuple[int, int], dict[str, Any]],
    ) -> int:
        return self.robot_component.unknown_cells_visible_from(position, cell_map)

    def choose_low_level_mdp_step(
        self,
        vehicle: dict[str, Any],
        snapshot: dict[str, Any],
        *,
        selected_next: set[tuple[int, int]],
        selected_edges: set[tuple[tuple[int, int], tuple[int, int]]],
    ) -> tuple[int, int] | None:
        return self.robot_component.choose_low_level_mdp_step(
            vehicle,
            snapshot,
            selected_next=selected_next,
            selected_edges=selected_edges,
        )

    def build_time_reservations(
        self,
        snapshot: dict[str, Any],
        *,
        exclude_task_id: str | None = None,
        horizon: int = 96,
    ) -> tuple[dict[int, set[tuple[int, int]]], set[tuple[tuple[int, int], tuple[int, int], int]]]:
        return self.navigator_component.build_time_reservations(
            snapshot,
            exclude_task_id=exclude_task_id,
            horizon=horizon,
        )

    def choose_frontier(self, vehicle: dict[str, Any], frontiers: list[dict[str, Any]]) -> dict[str, Any] | None:
        self.controller_component.assignment_policy = self.assignment_policy
        self.controller_component.scan_radius = self.scan_radius
        return self.controller_component.choose_frontier(vehicle, frontiers)

    def _build_random_vehicle_deployment(
        self,
        count: int | None = None,
        *,
        excluded: set[tuple[int, int]] | None = None,
        start_index: int = 0,
    ) -> dict[str, Any]:
        requested_count = max(1, min(12, int(count or self._default_vehicle_count())))
        excluded = excluded or set()
        obstacles = set(getattr(self.blackboard, "true_obstacles", set()))
        candidates = [
            (x, y)
            for y in range(1, self.blackboard.height - 1)
            for x in range(1, self.blackboard.width - 1)
            if (x, y) not in obstacles
            and (x, y) not in excluded
        ]
        if not candidates:
            raise ValueError("no free cell available for vehicle deployment")

        random.shuffle(candidates)
        selected = candidates[: min(requested_count, len(candidates))]
        return {
            "mode": "random",
            "count": len(selected),
            "vehicles": [
                {
                    "vehicleId": f"car-{index + 1:02d}",
                    "x": x,
                    "y": y,
                    "heading": random.choice([0, 90, 180, 270]),
                    "source": "RANDOM",
                    "adjusted": False,
                    "requested": None,
                }
                for index, (x, y) in enumerate(selected, start=start_index)
            ],
        }

    def _build_manual_vehicle_deployment(
        self,
        count: int | None,
        positions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        requested_count = max(1, min(12, int(count or len(positions) or self._default_vehicle_count())))
        selected: list[dict[str, Any]] = []
        occupied: set[tuple[int, int]] = set()
        vehicle_ids: set[str] = set()

        for index, item in enumerate(positions[:requested_count]):
            x, y = self._vehicle_position_from_payload(item)
            if not (0 <= x < self.blackboard.width and 0 <= y < self.blackboard.height):
                raise ValueError(f"vehicle position ({x}, {y}) is outside the map")
            if self.blackboard.is_truth_blocked({"x": x, "y": y}):
                raise ValueError(f"vehicle position ({x}, {y}) is blocked")
            if (x, y) in occupied:
                raise ValueError(f"duplicate vehicle position ({x}, {y})")

            vehicle_id = str(item.get("vehicleId") or item.get("id") or f"car-{index + 1:02d}")
            if vehicle_id in vehicle_ids:
                raise ValueError(f"duplicate vehicle id: {vehicle_id}")

            occupied.add((x, y))
            vehicle_ids.add(vehicle_id)
            selected.append(
                {
                    "vehicleId": vehicle_id,
                    "x": x,
                    "y": y,
                    "heading": int(item.get("heading", item.get("theta", 0))),
                    "source": "MANUAL",
                    "adjusted": False,
                    "requested": {"x": x, "y": y},
                }
            )

        if len(selected) < requested_count:
            fill = self._build_random_vehicle_deployment(
                requested_count - len(selected),
                excluded=occupied,
                start_index=len(selected),
            )
            for item in fill["vehicles"]:
                while item["vehicleId"] in vehicle_ids:
                    item["vehicleId"] = f"car-{len(vehicle_ids) + 1:02d}"
                vehicle_ids.add(item["vehicleId"])
                selected.append(item)

        return {
            "mode": "manual",
            "count": len(selected),
            "vehicles": selected,
        }

    @staticmethod
    def _vehicle_position_from_payload(item: dict[str, Any]) -> tuple[int, int]:
        if "x" in item and "y" in item:
            return int(item["x"]), int(item["y"])
        if isinstance(item.get("position"), dict):
            position = item["position"]
            return int(position["x"]), int(position["y"])
        if isinstance(item.get("pose"), dict) and isinstance(item["pose"].get("position"), dict):
            position = item["pose"]["position"]
            return int(position["x"]), int(position["y"])
        raise ValueError("vehicle position requires x/y, position, or pose.position")

    def _build_navigator_ids(self, count: int | None = None) -> list[str]:
        requested_count = max(1, min(12, int(count or 2)))
        return [f"navigator-{index + 1:02d}" for index in range(requested_count)]

    def _vehicle_deployment_count(self) -> int:
        vehicles = self.vehicle_deployment.get("vehicles") or []
        return int(self.vehicle_deployment.get("count") or len(vehicles) or self._default_vehicle_count())

    def _deployment_intersects_obstacles(self) -> bool:
        return any(
            self.blackboard.is_truth_blocked({"x": item["x"], "y": item["y"]})
            for item in self.vehicle_deployment.get("vehicles", [])
        )

    def _default_vehicle_count(self) -> int:
        return int(getattr(self._config, "num_vehicles", 3) or 3)
