from __future__ import annotations

from .astar_planner import AStarPlanner
from .base import PlannerProtocol
from .st_astar_planner import StAStarPlanner
from ...config import SimulationConfig


def create_planner(config: SimulationConfig, request: dict) -> PlannerProtocol:
    if request.get("avoidVehicles", True) and config.use_st_astar:
        return StAStarPlanner(config)
    return AStarPlanner(config)
