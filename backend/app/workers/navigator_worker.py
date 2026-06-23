from __future__ import annotations

import json
import os
import re
import signal
import time
from typing import Any

from ..navigator import NavigatorComponent
from ..redis import now_ms
from .common import (
    base_simulation_config,
    create_blackboard,
    env_float,
    env_int,
    heartbeat,
    read_runtime_config,
    should_run,
    worker_interval,
)


MAX_NAVIGATOR_PROCESSES = 12
NAVIGATOR_ID_PATTERN = re.compile(r"^navigator-(\d+)$")


def configured_navigator_ids(count: int) -> list[str]:
    return [f"navigator-{index + 1:02d}" for index in range(max(1, min(MAX_NAVIGATOR_PROCESSES, int(count or 2))))]


def explicit_navigator_id() -> str | None:
    component_id = os.getenv("COMPONENT_ID")
    if component_id and component_id.strip():
        return component_id.strip()
    navigator_id = os.getenv("NAVIGATOR_ID")
    if navigator_id and navigator_id.strip():
        return navigator_id.strip()
    legacy_ids = [item.strip() for item in os.getenv("NAVIGATOR_IDS", "").split(",") if item.strip()]
    return legacy_ids[0] if legacy_ids else None


def navigator_heartbeat_stale_after_ms() -> int:
    seconds = max(1.0, env_float("NAVIGATOR_HEARTBEAT_TTL_SECONDS", 10.0))
    return int(seconds * 1000)


def _navigator_index(navigator_id: str) -> int | None:
    match = NAVIGATOR_ID_PATTERN.match(navigator_id)
    return int(match.group(1)) if match else None


def _heartbeat_is_active(
    heartbeat_data: dict[str, Any],
    *,
    current_time_ms: int,
    stale_after_ms: int,
) -> bool:
    if heartbeat_data.get("componentType") != "NAVIGATOR":
        return False
    if heartbeat_data.get("status") == "OFFLINE":
        return False
    try:
        updated_at = int(heartbeat_data.get("updatedAt", 0))
    except (TypeError, ValueError):
        updated_at = 0
    return updated_at >= current_time_ms - stale_after_ms


def next_available_navigator_id(
    heartbeats: dict[str, dict[str, Any]],
    *,
    current_time_ms: int | None = None,
    stale_after_ms: int | None = None,
) -> str:
    current_time_ms = now_ms() if current_time_ms is None else current_time_ms
    stale_after_ms = navigator_heartbeat_stale_after_ms() if stale_after_ms is None else stale_after_ms
    active_ids = {
        component_id
        for component_id, item in heartbeats.items()
        if _heartbeat_is_active(item, current_time_ms=current_time_ms, stale_after_ms=stale_after_ms)
    }
    known_indexes = [
        index
        for component_id in heartbeats
        if (index := _navigator_index(component_id)) is not None
    ]
    search_limit = (max(known_indexes) + 1) if known_indexes else 1
    search_limit = min(MAX_NAVIGATOR_PROCESSES, search_limit)

    for navigator_id in configured_navigator_ids(search_limit):
        if navigator_id not in active_ids:
            return navigator_id
    raise RuntimeError(f"no free navigator id available; maximum is {MAX_NAVIGATOR_PROCESSES}")


def _load_navigator_heartbeats(blackboard) -> dict[str, dict[str, Any]]:
    raw = blackboard.redis.hgetall(blackboard.key("heartbeats"))
    heartbeats: dict[str, dict[str, Any]] = {}
    for component_id, value in raw.items():
        if component_id == "__empty__":
            continue
        try:
            heartbeat_data = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(heartbeat_data, dict) and heartbeat_data.get("componentType") == "NAVIGATOR":
            heartbeats[component_id] = heartbeat_data
    return heartbeats


def allocate_navigator_id(blackboard) -> str:
    lock = blackboard.redis.lock(
        blackboard.key("navigator:allocation"),
        timeout=10,
        blocking_timeout=10,
        thread_local=False,
    )
    with lock:
        navigator_id = next_available_navigator_id(_load_navigator_heartbeats(blackboard))
        heartbeat(blackboard, navigator_id, "NAVIGATOR", "READY", "starting")
        return navigator_id


def install_shutdown_handlers() -> None:
    def _stop(_signum, _frame) -> None:
        raise KeyboardInterrupt

    for signal_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        signum = getattr(signal, signal_name, None)
        if signum is not None:
            signal.signal(signum, _stop)


def main() -> None:
    blackboard = create_blackboard()
    base_config = base_simulation_config()
    config = read_runtime_config(blackboard, base_config)
    navigator_id = explicit_navigator_id() or allocate_navigator_id(blackboard)
    install_shutdown_handlers()
    navigator = NavigatorComponent(blackboard, config, [navigator_id])
    interval = worker_interval()
    print(f"[navigator] {navigator_id} connected to Redis prefix={blackboard.prefix}")

    try:
        while True:
            config = read_runtime_config(blackboard, base_config)
            navigator.config = config
            if should_run(blackboard):
                with blackboard.batch():
                    batches_per_tick = max(1, min(8, env_int("NAVIGATOR_BATCHES_PER_TICK", 2)))
                    for _ in range(batches_per_tick):
                        navigator.run_once()
                    heartbeat(blackboard, navigator_id, "NAVIGATOR", "READY", None)
            else:
                with blackboard.batch():
                    heartbeat(blackboard, navigator_id, "NAVIGATOR", "READY", None)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        heartbeat(blackboard, navigator_id, "NAVIGATOR", "OFFLINE", None)
        print(f"[navigator] {navigator_id} stopped")


if __name__ == "__main__":
    main()
