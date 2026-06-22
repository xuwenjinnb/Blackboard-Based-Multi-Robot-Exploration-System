from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RewardConfig:
    scan_radius: int = 2
    interaction_radius: int = 2
    new_cell_weight: float = 10.0
    repeated_cell_weight: float = 0.05
    repeat_mode: str = "team_overlap"
    reward_scale: float = 0.1
    reward_clip: float | None = 1.0
    interaction_weight: float = 0.1
    complete_bonus: float = 100.0
    step_penalty: float = -1.0
    interaction_soft_start: int = 2
    interaction_hard_limit: int = 7
    interaction_hard_penalty: float = -15.0


@dataclass(frozen=True)
class SimulationConfig:
    policy: str = "nearest"
    navigator_algorithm: str = "baseline"
    navigator_count: int = 2
    scan_radius: int = 2
    frontier_search_radius: int = 5
    use_st_astar: bool = True
    st_astar_horizon: int = 96
    cbs_max_nodes: int = 128
    low_level_mdp_horizon: int = 20
    low_level_mdp_discount: float = 0.80
    low_level_mdp_iterations: int = 50
    low_level_mdp_repulsion_weight: float = 8.0
    low_level_mdp_move_cost: float = 0.2


@dataclass(frozen=True)
class TrainingConfig:
    policy: str = "nearest"
    max_steps: int = 500
    gamma: float = 0.99
    batch_size: int = 16
    episodes: int = 250_000
    parallel_envs: int = 2
    obstacle_density_min: float = 0.10
    obstacle_density_max: float = 0.25
    num_vehicles: int = 3
    candidate_count: int = 4
    map_width: int = 32
    map_height: int = 24
    scan_radius: int = 2
    lstm_hidden: int = 64


@dataclass(frozen=True)
class RedisConfig:
    url: str = "redis://127.0.0.1:6379/0"
    prefix: str = "inspection"
    reset_on_start: bool = False
    map_width: int = 32
    map_height: int = 24
    map_chunk_size: int = 8


def simulation_config_from_env() -> SimulationConfig:
    return SimulationConfig(
        policy=os.getenv("INSPECTION_POLICY", "nearest"),
        navigator_algorithm=os.getenv("INSPECTION_NAVIGATOR_ALGORITHM", "baseline"),
        navigator_count=_env_int("INSPECTION_NAVIGATOR_COUNT", 2),
        scan_radius=_env_int("INSPECTION_SCAN_RADIUS", 2),
        frontier_search_radius=_env_int("INSPECTION_FRONTIER_SEARCH_RADIUS", 5),
        use_st_astar=_env_bool("INSPECTION_USE_ST_ASTAR", True),
        st_astar_horizon=_env_int("INSPECTION_ST_ASTAR_HORIZON", 96),
        cbs_max_nodes=_env_int("INSPECTION_CBS_MAX_NODES", 128),
        low_level_mdp_horizon=_env_int("INSPECTION_LOW_LEVEL_MDP_HORIZON", 20),
        low_level_mdp_discount=_env_float("INSPECTION_LOW_LEVEL_MDP_DISCOUNT", 0.80),
        low_level_mdp_iterations=_env_int("INSPECTION_LOW_LEVEL_MDP_ITERATIONS", 50),
        low_level_mdp_repulsion_weight=_env_float("INSPECTION_LOW_LEVEL_MDP_REPULSION_WEIGHT", 8.0),
        low_level_mdp_move_cost=_env_float("INSPECTION_LOW_LEVEL_MDP_MOVE_COST", 0.2),
    )


def redis_config_from_env() -> RedisConfig:
    return RedisConfig(
        url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        prefix=os.getenv("REDIS_PREFIX", "inspection"),
        reset_on_start=_env_bool("REDIS_RESET_ON_START", False),
        map_width=_env_int("INSPECTION_MAP_WIDTH", 32),
        map_height=_env_int("INSPECTION_MAP_HEIGHT", 24),
        map_chunk_size=_env_int("INSPECTION_MAP_CHUNK_SIZE", 8),
    )


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default
