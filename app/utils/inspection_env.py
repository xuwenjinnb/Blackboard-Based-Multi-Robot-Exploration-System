from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from ..blackboard import Blackboard
from ..config import RewardConfig, SimulationConfig, TrainingConfig
from ..controller.policies import AssignmentPolicy, create_assignment_policy
from .rewards import ExplorationReward
from ..simulation import SimulationEngine


@dataclass(frozen=True)
class EnvStep:
    observation: dict[str, Any]
    reward: float
    terminated: bool
    truncated: bool
    info: dict[str, Any]


class InspectionEnv:
    def __init__(
        self,
        *,
        width: int = 32,
        height: int = 24,
        max_steps: int = 500,
        assignment_policy: AssignmentPolicy | None = None,
        simulation_config: SimulationConfig | None = None,
        reward_config: RewardConfig | None = None,
        training_config: TrainingConfig | None = None,
        randomize_layout: bool = False,
        seed: int | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.max_steps = max_steps
        self.simulation_config = simulation_config or SimulationConfig()
        self.training_config = training_config or TrainingConfig(
            policy=self.simulation_config.policy,
            max_steps=max_steps,
            map_width=width,
            map_height=height,
            scan_radius=self.simulation_config.scan_radius,
        )
        self.reward_config = reward_config or RewardConfig(scan_radius=self.simulation_config.scan_radius)
        self.assignment_policy = assignment_policy or create_assignment_policy(self.simulation_config.policy)
        self.randomize_layout = randomize_layout
        self.rng = random.Random(seed)
        self.blackboard = Blackboard(width=width, height=height)
        self.engine = SimulationEngine(
            self.blackboard,
            assignment_policy=self.assignment_policy,
            config=self.simulation_config,
        )
        self.reward_model = ExplorationReward(self.reward_config)
        self.steps = 0
        self.last_metrics: dict[str, Any] | None = None

    def reset(self) -> dict[str, Any]:
        self.blackboard.reset()
        self.engine.tick = 0
        self.engine.movement_steps = 0
        self.steps = 0
        self.reward_model.reset()
        self.blackboard.set_system_status("RUNNING")
        if self.randomize_layout:
            self._randomize_episode()
        else:
            self.engine.ensure_demo_vehicles()
        snapshot = self.blackboard.snapshot()
        self.last_metrics = self.metrics(snapshot)
        return snapshot

    def step(self, action: Any = None) -> EnvStep:
        del action
        if self.last_metrics is None:
            self.reset()

        before_snapshot = self.blackboard.snapshot()
        self.engine.step()
        self.steps += 1

        snapshot = self.blackboard.snapshot()
        after = self.metrics(snapshot)
        reward_step = self.reward_model.compute(before_snapshot, snapshot)
        reward = reward_step.team_reward
        terminated = bool(after["complete"])
        if terminated and not reward_step.breakdown.get("complete", False):
            reward += self.reward_config.complete_bonus
            reward_step.breakdown["reachableCompletionBonus"] = self.reward_config.complete_bonus
        truncated = self.steps >= self.max_steps and not terminated
        self.last_metrics = after

        return EnvStep(
            observation=snapshot,
            reward=reward,
            terminated=terminated,
            truncated=truncated,
            info={
                "metrics": after,
                "policy": self.assignment_policy.name,
                "individualRewards": reward_step.individual_rewards,
                "rewardBreakdown": reward_step.breakdown,
            },
        )

    def run_episode(self) -> list[dict[str, Any]]:
        self.reset()
        curve = [self._curve_point(0, 0.0, self.last_metrics or {})]

        while True:
            result = self.step()
            metrics = result.info["metrics"]
            curve.append(self._curve_point(self.steps, result.reward, metrics))
            if result.terminated or result.truncated:
                break

        return curve

    def metrics(self, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        snapshot = snapshot or self.blackboard.snapshot()
        cells = snapshot["map"]["cells"]
        total = len(cells)
        unknown = sum(1 for cell in cells if cell.get("state") == "UNKNOWN")
        free = sum(1 for cell in cells if cell.get("state") == "FREE")
        visited = sum(1 for cell in cells if cell.get("state") == "VISITED")
        obstacle = sum(1 for cell in cells if cell.get("state") == "OBSTACLE")
        known = total - unknown
        reachable = reachable_free_cells(
            self.width,
            self.height,
            self.blackboard.true_obstacles,
            [
                (int(vehicle["pose"]["position"]["x"]), int(vehicle["pose"]["position"]["y"]))
                for vehicle in snapshot.get("vehicles", [])
            ],
        )
        cell_state = {
            (int(cell["x"]), int(cell["y"])): cell.get("state", "UNKNOWN")
            for cell in cells
        }
        reachable_total = len(reachable)
        reachable_unknown = sum(1 for point in reachable if cell_state.get(point) == "UNKNOWN")
        reachable_known = reachable_total - reachable_unknown

        return {
            "tick": self.engine.tick,
            "movementSteps": self.engine.movement_steps,
            "steps": self.steps,
            "totalCells": total,
            "knownCells": known,
            "unknownCells": unknown,
            "freeCells": free,
            "visitedCells": visited,
            "obstacleCells": obstacle,
            "mapCoverage": known / total if total else 0.0,
            "reachableCells": reachable_total,
            "reachableKnownCells": reachable_known,
            "reachableUnknownCells": reachable_unknown,
            "coverage": reachable_known / reachable_total if reachable_total else 0.0,
            "openFrontiers": sum(
                1 for frontier in snapshot["frontiers"] if frontier.get("status") == "OPEN"
            ),
            "assignedFrontiers": sum(
                1 for frontier in snapshot["frontiers"] if frontier.get("status") == "ASSIGNED"
            ),
            "doneTasks": sum(1 for task in snapshot["tasks"] if task.get("status") == "DONE"),
            "localInteractionPairs": sum(
                1 for count in self.reward_model.interaction_counts.values() if count > 0
            ),
            "activeTasks": sum(
                1
                for task in snapshot["tasks"]
                if task.get("status") not in {"DONE", "FAILED", "CANCELLED"}
            ),
            "complete": reachable_total > 0 and reachable_unknown == 0,
        }

    def _randomize_episode(self) -> None:
        density = self.rng.uniform(
            self.training_config.obstacle_density_min,
            self.training_config.obstacle_density_max,
        )
        obstacles = randomized_connected_obstacles(self.width, self.height, density, self.rng)
        free_cells = [
            (x, y)
            for y in range(1, self.height - 1)
            for x in range(1, self.width - 1)
            if (x, y) not in obstacles
        ]
        self.rng.shuffle(free_cells)

        vehicle_count = min(self.training_config.num_vehicles, len(free_cells))
        with self.blackboard.lock:
            self.blackboard.true_obstacles = obstacles

        for index in range(vehicle_count):
            x, y = free_cells[index]
            vehicle_id = f"car-{index + 1:02d}"
            pose = {
                "position": {"x": x, "y": y},
                "heading": self.rng.choice([0, 90, 180, 270]),
            }
            self.blackboard.register_vehicle(vehicle_id, pose)
            self.scan_initial(vehicle_id)

        for navigator_id in self.engine.navigator_ids:
            self.blackboard.update_heartbeat(navigator_id, "NAVIGATOR", "READY", None)
        self.blackboard.update_heartbeat("controller-01", "CONTROLLER", "READY", None)

    def scan_initial(self, vehicle_id: str) -> None:
        self.engine.scan_and_upload(vehicle_id)

    def _curve_point(self, step: int, reward: float, metrics: dict[str, Any]) -> dict[str, Any]:
        return {
            "step": step,
            "tick": metrics.get("tick", self.engine.tick),
            "reward": reward,
            "coverage": metrics.get("coverage", 0.0),
            "mapCoverage": metrics.get("mapCoverage", 0.0),
            "knownCells": metrics.get("knownCells", 0),
            "unknownCells": metrics.get("unknownCells", self.width * self.height),
            "reachableCells": metrics.get("reachableCells", 0),
            "reachableKnownCells": metrics.get("reachableKnownCells", 0),
            "reachableUnknownCells": metrics.get("reachableUnknownCells", 0),
            "openFrontiers": metrics.get("openFrontiers", 0),
            "activeTasks": metrics.get("activeTasks", 0),
            "doneTasks": metrics.get("doneTasks", 0),
        }


def randomized_obstacles(
    width: int,
    height: int,
    density: float,
    rng: random.Random,
) -> set[tuple[int, int]]:
    obstacles: set[tuple[int, int]] = set()
    for x in range(width):
        obstacles.add((x, 0))
        obstacles.add((x, height - 1))
    for y in range(height):
        obstacles.add((0, y))
        obstacles.add((width - 1, y))

    interior = [
        (x, y)
        for y in range(1, height - 1)
        for x in range(1, width - 1)
    ]
    rng.shuffle(interior)
    count = min(len(interior), max(0, int(len(interior) * density)))
    obstacles.update(interior[:count])
    return obstacles


def randomized_connected_obstacles(
    width: int,
    height: int,
    density: float,
    rng: random.Random,
) -> set[tuple[int, int]]:
    obstacles = border_obstacles(width, height)
    interior = [
        (x, y)
        for y in range(1, height - 1)
        for x in range(1, width - 1)
    ]
    if not interior:
        return obstacles

    obstacle_count = min(len(interior) - 1, max(0, int(len(interior) * density)))
    target_free_count = len(interior) - obstacle_count
    start = rng.choice(interior)
    free: set[tuple[int, int]] = {start}
    frontier = [neighbor for neighbor in grid_neighbors4(start) if neighbor in interior]

    while len(free) < target_free_count and frontier:
        index = rng.randrange(len(frontier))
        cell = frontier.pop(index)
        if cell in free:
            continue
        free.add(cell)
        neighbors = [neighbor for neighbor in grid_neighbors4(cell) if neighbor in interior and neighbor not in free]
        rng.shuffle(neighbors)
        frontier.extend(neighbors)

    if len(free) < target_free_count:
        for cell in interior:
            if len(free) >= target_free_count:
                break
            free.add(cell)

    obstacles.update(cell for cell in interior if cell not in free)
    return obstacles


def border_obstacles(width: int, height: int) -> set[tuple[int, int]]:
    obstacles: set[tuple[int, int]] = set()
    for x in range(width):
        obstacles.add((x, 0))
        obstacles.add((x, height - 1))
    for y in range(height):
        obstacles.add((0, y))
        obstacles.add((width - 1, y))
    return obstacles


def reachable_free_cells(
    width: int,
    height: int,
    obstacles: set[tuple[int, int]],
    starts: list[tuple[int, int]],
) -> set[tuple[int, int]]:
    reachable: set[tuple[int, int]] = set()
    queue = [
        start
        for start in starts
        if 0 <= start[0] < width and 0 <= start[1] < height and start not in obstacles
    ]

    while queue:
        current = queue.pop(0)
        if current in reachable:
            continue
        reachable.add(current)
        for neighbor in grid_neighbors4(current):
            if not (0 <= neighbor[0] < width and 0 <= neighbor[1] < height):
                continue
            if neighbor in obstacles or neighbor in reachable:
                continue
            queue.append(neighbor)

    return reachable


def grid_neighbors4(point: tuple[int, int]) -> list[tuple[int, int]]:
    x, y = point
    return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
