from __future__ import annotations

import os
import socket
import time
from dataclasses import replace
from typing import Any

from ..redis import now_ms
from ..config import SimulationConfig, simulation_config_from_env
from ..controller.policies import AssignmentPolicy, create_assignment_policy
from ..redis import (
    RedisBlackboard,
    TRANSIENT_REDIS_ERRORS,
    log_transient_redis_error,
    redis_config_from_env,
)


RUNTIME_HASH = "runtime"


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def host_name() -> str:
    return os.getenv("COMPONENT_HOST") or os.getenv("COMPUTERNAME") or socket.gethostname()


def worker_interval(default: float = 0.45) -> float:
    return max(0.05, env_float("WORKER_INTERVAL_SECONDS", default))


def create_blackboard(wait: bool = True) -> RedisBlackboard:
    config = redis_config_from_env()
    while True:
        try:
            return RedisBlackboard(
                config,
                prefix=config.prefix,
                width=config.map_width,
                height=config.map_height,
                chunk_size=config.map_chunk_size,
                reset_on_start=config.reset_on_start,
            )
        except TRANSIENT_REDIS_ERRORS as exc:
            if not wait:
                raise
            print(f"[worker] Redis unavailable: {exc}. Retrying in 2s...")
            time.sleep(2)


def read_runtime_config(blackboard: RedisBlackboard, fallback: SimulationConfig) -> SimulationConfig:
    raw: dict[str, Any] = blackboard.redis.hgetall(blackboard.key(RUNTIME_HASH))
    policy = raw.get("policy") or fallback.policy
    navigator_algorithm = raw.get("navigatorAlgorithm") or fallback.navigator_algorithm
    return replace(
        fallback,
        policy=str(policy),
        navigator_algorithm=str(navigator_algorithm),
    )


def persist_runtime_config(blackboard: RedisBlackboard, config: SimulationConfig) -> None:
    blackboard.redis.hset(
        blackboard.key(RUNTIME_HASH),
        mapping={
            "policy": config.policy,
            "navigatorAlgorithm": config.navigator_algorithm,
            "updatedAt": str(now_ms()),
        },
    )


def _runtime_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def create_policy(config: SimulationConfig) -> AssignmentPolicy:
    return create_assignment_policy(config.policy)


def heartbeat(
    blackboard: RedisBlackboard,
    component_id: str,
    component_type: str,
    status: str,
    current_work_id: str | None = None,
) -> None:
    blackboard.update_heartbeat(
        component_id,
        component_type,
        status,
        current_work_id,
        host_name(),
        os.getpid(),
    )


def should_run(blackboard: RedisBlackboard) -> bool:
    return blackboard.system_status == "RUNNING"


def base_simulation_config() -> SimulationConfig:
    return simulation_config_from_env()
