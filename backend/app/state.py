from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi import HTTPException

from .config import simulation_config_from_env
from .controller.policies import create_assignment_policy
from .redis import AuthStore, RedisBlackboard, ReplayStore, now_ms, redis_config_from_env
from .simulation import SimulationEngine
from .workers.common import env_bool, env_float, persist_runtime_config


redis_config = redis_config_from_env()
blackboard = RedisBlackboard(
    redis_config,
    prefix=redis_config.prefix,
    width=redis_config.map_width,
    height=redis_config.map_height,
    chunk_size=redis_config.map_chunk_size,
    reset_on_start=redis_config.reset_on_start,
)
auth_store = AuthStore(blackboard.redis, redis_config.prefix)
replay_store = ReplayStore(blackboard.redis, redis_config.prefix)
simulation_config = simulation_config_from_env()
startup_policy = simulation_config.policy
assignment_policy = create_assignment_policy(startup_policy)
simulation = SimulationEngine(blackboard, assignment_policy=assignment_policy, config=simulation_config)
embedded_simulation_enabled = env_bool("RUN_EMBEDDED_SIMULATION", True)
broadcast_interval = max(0.15, env_float("BROADCAST_INTERVAL_SECONDS", 0.3))
persist_runtime_config(blackboard, simulation.config)

POLICY_OPTIONS = [
    {
        "id": "nearest",
        "name": "Nearest reachable frontier",
        "summary": "Use A* to verify reachability, then choose the nearest frontier.",
    },
    {
        "id": "greedy",
        "name": "Greedy information gain",
        "summary": "Prefer frontiers with higher unknown-cell gain and lower travel cost.",
    },
    {
        "id": "low_mdp",
        "name": "Low-level MDP",
        "summary": "Move by local value iteration and use a repulsion field to reduce clustering.",
    },
]

NAVIGATOR_OPTIONS = [
    {
        "id": "baseline",
        "name": "Baseline",
        "summary": "Plan each navigation request with A* or space-time A* reservations.",
    },
    {
        "id": "cbs",
        "name": "CBS",
        "summary": "Batch pending requests, detect path conflicts, and replan with constraints.",
    },
]


def normalize_policy(policy: str | None) -> str:
    key = (policy or "nearest").strip().lower()
    aliases = {
        "nearest-reachable": "nearest",
        "nearest-reachable-frontier": "nearest",
        "greedy-frontier": "greedy",
        "gain": "greedy",
        "low-mdp": "low_mdp",
        "low-level-mdp": "low_mdp",
        "low_level_mdp": "low_mdp",
    }
    key = aliases.get(key, key)
    valid = {item["id"] for item in POLICY_OPTIONS}
    if key not in valid:
        raise HTTPException(status_code=400, detail=f"unknown policy: {policy}")
    return key


def normalize_navigator_algorithm(algorithm: str | None) -> str:
    key = (algorithm or "baseline").strip().lower()
    aliases = {
        "base": "baseline",
        "st_astar": "baseline",
        "st-astar": "baseline",
        "reservation": "baseline",
        "reservations": "baseline",
        "conflict-based-search": "cbs",
    }
    key = aliases.get(key, key)
    valid = {item["id"] for item in NAVIGATOR_OPTIONS}
    if key not in valid:
        raise HTTPException(status_code=400, detail=f"unknown navigator algorithm: {algorithm}")
    return key


def configure_policy(policy: str) -> dict[str, Any]:
    normalized = normalize_policy(policy)
    try:
        assignment_policy = create_assignment_policy(normalized)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    simulation.config = replace(simulation.config, policy=normalized)
    simulation.assignment_policy = assignment_policy
    persist_runtime_config(blackboard, simulation.config)
    blackboard.add_event("controller", "POLICY_CHANGED", f"Policy switched to {normalized}")
    return runtime_state()


def configure_navigator_algorithm(algorithm: str) -> dict[str, Any]:
    normalized = normalize_navigator_algorithm(algorithm)
    simulation.config = replace(simulation.config, navigator_algorithm=normalized)
    persist_runtime_config(blackboard, simulation.config)
    blackboard.add_event("navigator", "NAVIGATOR_CHANGED", f"Navigator algorithm switched to {normalized}")
    return runtime_state()


def active_navigator_heartbeats() -> list[dict[str, Any]]:
    stale_after_ms = int(max(1.0, env_float("NAVIGATOR_HEARTBEAT_TTL_SECONDS", 10.0)) * 1000)
    minimum_updated_at = now_ms() - stale_after_ms
    snapshot = blackboard.snapshot()
    navigators = [
        heartbeat
        for heartbeat in snapshot.get("heartbeats", [])
        if heartbeat.get("componentType") == "NAVIGATOR"
        and heartbeat.get("status") != "OFFLINE"
        and int(heartbeat.get("updatedAt") or 0) >= minimum_updated_at
    ]
    navigators.sort(key=lambda item: str(item.get("componentId", "")))
    return navigators


def runtime_state() -> dict[str, Any]:
    navigator_heartbeats = active_navigator_heartbeats()
    return {
        "map": {
            "width": blackboard.width,
            "height": blackboard.height,
            "chunkSize": blackboard.chunk_size,
        },
        "policy": simulation.config.policy,
        "assignmentPolicy": getattr(simulation.assignment_policy, "name", simulation.config.policy),
        "policies": POLICY_OPTIONS,
        "navigatorAlgorithm": simulation.config.navigator_algorithm,
        "navigatorAlgorithms": NAVIGATOR_OPTIONS,
        "navigatorCount": len(navigator_heartbeats),
        "navigatorIds": [item["componentId"] for item in navigator_heartbeats],
        "navigatorHeartbeats": navigator_heartbeats,
        "vehicleDeployment": simulation.vehicle_deployment,
        "tick": simulation.tick,
        "movementSteps": simulation.movement_steps,
        "scanRadius": simulation.config.scan_radius,
        "useStAstar": simulation.config.use_st_astar,
        "stAstarHorizon": simulation.config.st_astar_horizon,
        "embeddedSimulation": embedded_simulation_enabled,
        "broadcastInterval": broadcast_interval,
    }


def snapshot_with_runtime(
    map_version: int | None = None,
    map_generation: int | None = None,
) -> dict[str, Any]:
    snapshot = blackboard.snapshot_since(map_version, map_generation)
    snapshot["runtime"] = runtime_state()
    return snapshot


def snapshot_map_cursor(snapshot: dict[str, Any]) -> tuple[int, int] | None:
    if snapshot.get("mapDelta"):
        return int(snapshot["mapDelta"]["toVersion"]), int(snapshot["mapDelta"].get("generation", 0))
    if snapshot.get("map"):
        return int(snapshot["map"].get("version", 0)), int(snapshot["map"].get("generation", 0))
    return None
