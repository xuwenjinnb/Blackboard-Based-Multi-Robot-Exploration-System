from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SimulationConfig:
    policy: str = "nearest"
    navigator_algorithm: str = "baseline"
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
    num_vehicles: int = 8


def simulation_config_from_env() -> SimulationConfig:
    return SimulationConfig(
        policy=os.getenv("INSPECTION_POLICY", "nearest"),
        navigator_algorithm=os.getenv("INSPECTION_NAVIGATOR_ALGORITHM", "baseline"),
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
