from __future__ import annotations

import os
import time

from ..navigator import NavigatorComponent
from .common import (
    base_simulation_config,
    create_blackboard,
    env_int,
    heartbeat,
    read_runtime_config,
    should_run,
    worker_interval,
)


def configured_navigator_ids(count: int) -> list[str]:
    return [f"navigator-{index + 1:02d}" for index in range(max(1, min(12, int(count or 2))))]


def explicit_navigator_ids() -> list[str] | None:
    raw = os.getenv("NAVIGATOR_IDS")
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    component_id = os.getenv("COMPONENT_ID")
    return [component_id] if component_id else None


def main() -> None:
    explicit_ids = explicit_navigator_ids()
    blackboard = create_blackboard()
    base_config = base_simulation_config()
    config = read_runtime_config(blackboard, base_config)
    ids = explicit_ids or configured_navigator_ids(config.navigator_count)
    primary_id = ids[0]
    navigator = NavigatorComponent(blackboard, config, ids)
    interval = worker_interval()
    print(f"[navigator] {','.join(ids)} connected to Redis prefix={blackboard.prefix}")

    try:
        while True:
            config = read_runtime_config(blackboard, base_config)
            navigator.config = config
            if explicit_ids is None:
                ids = configured_navigator_ids(config.navigator_count)
                primary_id = ids[0]
                navigator.navigator_ids = ids
            if should_run(blackboard):
                with blackboard.batch():
                    batches_per_tick = max(1, min(8, env_int("NAVIGATOR_BATCHES_PER_TICK", 2)))
                    for _ in range(batches_per_tick):
                        navigator.run_once()
                    for navigator_id in ids:
                        heartbeat(blackboard, navigator_id, "NAVIGATOR", "READY", None)
            else:
                with blackboard.batch():
                    heartbeat(blackboard, primary_id, "NAVIGATOR", "READY", None)
            time.sleep(interval)
    except KeyboardInterrupt:
        for navigator_id in ids:
            heartbeat(blackboard, navigator_id, "NAVIGATOR", "OFFLINE", None)
        print(f"[navigator] {','.join(ids)} stopped")


if __name__ == "__main__":
    main()
