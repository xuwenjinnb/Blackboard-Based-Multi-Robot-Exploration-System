from __future__ import annotations

from .base import AssignmentPolicy
from .greedy_frontier import GreedyFrontierPolicy
from .nearest_reachable_frontier import NearestReachableFrontierPolicy
from .noop import NoopAssignmentPolicy


def create_assignment_policy(name: str | None) -> AssignmentPolicy:
    key = (name or "nearest").strip().lower()
    if key in {"low_mdp", "low-mdp", "low-level-mdp", "low_level_mdp"}:
        return NoopAssignmentPolicy()
    if key in {"nearest", "nearest-reachable", "nearest-reachable-frontier"}:
        return NearestReachableFrontierPolicy()
    if key in {"greedy", "greedy-frontier", "gain"}:
        return GreedyFrontierPolicy()
    raise ValueError(f"unknown assignment policy: {name}")
