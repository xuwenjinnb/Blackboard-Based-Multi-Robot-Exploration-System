from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .common import (
    base_simulation_config,
    create_blackboard,
    env_float,
    heartbeat,
    log_transient_redis_error,
    read_runtime_config,
    TRANSIENT_REDIS_ERRORS,
)
from .navigator_worker import configured_navigator_ids


ChildMap = dict[str, subprocess.Popen]


def supervisor_interval() -> float:
    return max(0.2, env_float("NAVIGATOR_SUPERVISOR_INTERVAL_SECONDS", 0.75))


def backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def desired_navigator_ids(blackboard, fallback_config) -> list[str]:
    config = read_runtime_config(blackboard, fallback_config)
    return configured_navigator_ids(config.navigator_count)


def start_navigator_child(navigator_id: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["COMPONENT_ID"] = navigator_id
    env.pop("NAVIGATOR_IDS", None)
    env.setdefault("NAVIGATOR_BATCHES_PER_TICK", "1")

    child = subprocess.Popen(
        [sys.executable, "-u", "-m", "app.workers.navigator_worker"],
        cwd=str(backend_dir()),
        env=env,
    )
    print(f"[navigator-supervisor] started {navigator_id} pid={child.pid}")
    return child


def stop_navigator_child(navigator_id: str, child: subprocess.Popen) -> None:
    if child.poll() is not None:
        print(f"[navigator-supervisor] {navigator_id} already exited code={child.returncode}")
        return

    print(f"[navigator-supervisor] stopping {navigator_id} pid={child.pid}")
    child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)


def reconcile_children(children: ChildMap, desired_ids: list[str]) -> None:
    desired = set(desired_ids)

    for navigator_id, child in list(children.items()):
        if child.poll() is not None:
            print(f"[navigator-supervisor] {navigator_id} exited code={child.returncode}")
            del children[navigator_id]

    for navigator_id, child in list(children.items()):
        if navigator_id not in desired:
            stop_navigator_child(navigator_id, child)
            del children[navigator_id]

    for navigator_id in desired_ids:
        if navigator_id not in children:
            children[navigator_id] = start_navigator_child(navigator_id)


def stop_all(children: ChildMap) -> None:
    for navigator_id, child in list(children.items()):
        stop_navigator_child(navigator_id, child)
        del children[navigator_id]


def main() -> None:
    blackboard = create_blackboard()
    fallback_config = base_simulation_config()
    children: ChildMap = {}
    interval = supervisor_interval()
    print(f"[navigator-supervisor] connected to Redis prefix={blackboard.prefix}")

    try:
        while True:
            try:
                desired_ids = desired_navigator_ids(blackboard, fallback_config)
                reconcile_children(children, desired_ids)
                heartbeat(
                    blackboard,
                    "navigator-supervisor",
                    "NAVIGATOR_SUPERVISOR",
                    "READY",
                    f"{len(children)}/{len(desired_ids)} navigators",
                )
            except TRANSIENT_REDIS_ERRORS as exc:
                log_transient_redis_error("navigator-supervisor", exc)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("[navigator-supervisor] stopping children")
    finally:
        stop_all(children)
        heartbeat(blackboard, "navigator-supervisor", "NAVIGATOR_SUPERVISOR", "OFFLINE", None)


if __name__ == "__main__":
    main()
