from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from ..config import RewardConfig
from ..pathfinding import manhattan


@dataclass(frozen=True)
class RewardStep:
    team_reward: float
    individual_rewards: dict[str, float]
    breakdown: dict[str, Any]


class ExplorationReward:
    def __init__(self, config: RewardConfig | None = None) -> None:
        self.config = config or RewardConfig()
        self.interaction_counts: dict[tuple[str, str], int] = {}

    def reset(self) -> None:
        self.interaction_counts.clear()

    def compute(self, before: dict[str, Any], after: dict[str, Any]) -> RewardStep:
        before_cells = {
            (int(cell["x"]), int(cell["y"])): cell.get("state", "UNKNOWN")
            for cell in before["map"]["cells"]
        }
        after_cells = {
            (int(cell["x"]), int(cell["y"])): cell.get("state", "UNKNOWN")
            for cell in after["map"]["cells"]
        }
        width = int(after["map"]["width"])
        height = int(after["map"]["height"])
        vehicles = after.get("vehicles", [])

        individual_rewards: dict[str, float] = {}
        individual_breakdown: dict[str, dict[str, float]] = {}
        observed_by_vehicle: dict[str, set[tuple[int, int]]] = {}
        team_observed: set[tuple[int, int]] = set()

        for vehicle in vehicles:
            vehicle_id = vehicle["vehicleId"]
            observed = observed_cells(
                vehicle["pose"]["position"],
                self.config.scan_radius,
                width,
                height,
            )
            observed_by_vehicle[vehicle_id] = observed
            team_observed.update(observed)

        overlapped = overlapped_cells(observed_by_vehicle)

        for vehicle in vehicles:
            vehicle_id = vehicle["vehicleId"]
            observed = observed_by_vehicle[vehicle_id]
            new_count = count_new_cells(observed, before_cells, after_cells)
            repeat_count = self.count_repeat(observed, before_cells, overlapped)
            raw_reward = float(
                self.config.new_cell_weight * new_count
                - self.config.repeated_cell_weight * repeat_count
            )
            individual_rewards[vehicle_id] = scale_and_clip(raw_reward, self.config)
            individual_breakdown[vehicle_id] = {
                "newCells": float(new_count),
                "repeatedCells": float(repeat_count),
                "interactionPenalty": 0.0,
                "rawRewardBeforeInteraction": raw_reward,
            }

        pair_penalties = self._update_interactions(vehicles)
        for (left_id, right_id), penalty in pair_penalties.items():
            scaled_penalty = self.config.interaction_weight * penalty
            individual_rewards[left_id] = scale_and_clip(
                individual_rewards.get(left_id, 0.0) + scaled_penalty,
                self.config,
                already_scaled=True,
            )
            individual_rewards[right_id] = scale_and_clip(
                individual_rewards.get(right_id, 0.0) + scaled_penalty,
                self.config,
                already_scaled=True,
            )
            individual_breakdown[left_id]["interactionPenalty"] += scaled_penalty
            individual_breakdown[right_id]["interactionPenalty"] += scaled_penalty

        team_new = count_new_cells(team_observed, before_cells, after_cells)
        team_repeat = self.count_repeat(team_observed, before_cells, overlapped)
        complete = all(state != "UNKNOWN" for state in after_cells.values())
        raw_team_reward = float(
            self.config.new_cell_weight * team_new
            - self.config.repeated_cell_weight * team_repeat
            + self.config.step_penalty
        )
        team_reward = scale_and_clip(raw_team_reward, self.config)
        if complete:
            team_reward += self.config.complete_bonus

        return RewardStep(
            team_reward=team_reward,
            individual_rewards=individual_rewards,
            breakdown={
                "teamNewCells": team_new,
                "teamRepeatedCells": team_repeat,
                "newCellWeight": self.config.new_cell_weight,
                "repeatedCellWeight": self.config.repeated_cell_weight,
                "repeatMode": self.config.repeat_mode,
                "rewardScale": self.config.reward_scale,
                "rewardClip": self.config.reward_clip,
                "rawTeamReward": raw_team_reward,
                "stepPenalty": self.config.step_penalty,
                "completeBonus": self.config.complete_bonus if complete else 0.0,
                "complete": complete,
                "individual": individual_breakdown,
                "interactionCounts": {
                    f"{left}/{right}": count
                    for (left, right), count in sorted(self.interaction_counts.items())
                },
            },
        )

    def count_repeat(
        self,
        observed: set[tuple[int, int]],
        before_cells: dict[tuple[int, int], str],
        overlapped: set[tuple[int, int]],
    ) -> int:
        if self.config.repeat_mode == "none":
            return 0
        if self.config.repeat_mode == "team_overlap":
            return count_repeated_cells(observed & overlapped, before_cells)
        return count_repeated_cells(observed, before_cells)

    def _update_interactions(
        self,
        vehicles: list[dict[str, Any]],
    ) -> dict[tuple[str, str], float]:
        active_pairs: set[tuple[str, str]] = set()
        penalties: dict[tuple[str, str], float] = {}

        for left, right in combinations(vehicles, 2):
            left_id = left["vehicleId"]
            right_id = right["vehicleId"]
            pair = tuple(sorted((left_id, right_id)))
            if manhattan(left["pose"]["position"], right["pose"]["position"]) <= self.config.interaction_radius:
                active_pairs.add(pair)
                rho = self.interaction_counts.get(pair, 0) + 1
                self.interaction_counts[pair] = rho
                penalties[pair] = interaction_penalty(rho, self.config)

        for pair in list(self.interaction_counts):
            if pair not in active_pairs:
                self.interaction_counts.pop(pair, None)

        return penalties


def observed_cells(
    center: dict[str, int],
    radius: int,
    width: int,
    height: int,
) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    for y in range(int(center["y"]) - radius, int(center["y"]) + radius + 1):
        for x in range(int(center["x"]) - radius, int(center["x"]) + radius + 1):
            if 0 <= x < width and 0 <= y < height:
                cells.add((x, y))
    return cells


def count_new_cells(
    observed: set[tuple[int, int]],
    before_cells: dict[tuple[int, int], str],
    after_cells: dict[tuple[int, int], str],
) -> int:
    return sum(
        1
        for cell in observed
        if before_cells.get(cell) == "UNKNOWN" and after_cells.get(cell) != "UNKNOWN"
    )


def count_repeated_cells(
    observed: set[tuple[int, int]],
    before_cells: dict[tuple[int, int], str],
) -> int:
    return sum(1 for cell in observed if before_cells.get(cell) != "UNKNOWN")


def overlapped_cells(observed_by_vehicle: dict[str, set[tuple[int, int]]]) -> set[tuple[int, int]]:
    counts: dict[tuple[int, int], int] = {}
    for observed in observed_by_vehicle.values():
        for cell in observed:
            counts[cell] = counts.get(cell, 0) + 1
    return {cell for cell, count in counts.items() if count > 1}


def scale_and_clip(
    value: float,
    config: RewardConfig,
    *,
    already_scaled: bool = False,
) -> float:
    scaled = value if already_scaled else value * config.reward_scale
    if config.reward_clip is None:
        return scaled
    return max(-config.reward_clip, min(config.reward_clip, scaled))


def interaction_penalty(rho: int, config: RewardConfig) -> float:
    if rho < config.interaction_soft_start:
        return 0.0
    if rho > config.interaction_hard_limit:
        return config.interaction_hard_penalty
    return -math.sqrt(0.2 * math.exp(rho))
