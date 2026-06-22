from __future__ import annotations

import os
import time

from ..controller import ControllerComponent
from .common import (
    base_simulation_config,
    create_blackboard,
    create_policy,
    env_bool,
    env_int,
    heartbeat,
    host_name,
    read_runtime_config,
    should_run,
    worker_interval,
)


def controller_lock_key(blackboard) -> str:
    return blackboard.key("locks:controller")


def acquire_controller_lock(blackboard, owner: str, ttl_seconds: int) -> bool:
    return bool(blackboard.redis.set(controller_lock_key(blackboard), owner, nx=True, ex=ttl_seconds))


def refresh_controller_lock(blackboard, owner: str, ttl_seconds: int) -> bool:
    key = controller_lock_key(blackboard)
    if blackboard.redis.get(key) != owner:
        return False
    blackboard.redis.expire(key, ttl_seconds)
    return True


def release_controller_lock(blackboard, owner: str) -> None:
    key = controller_lock_key(blackboard)
    if blackboard.redis.get(key) == owner:
        blackboard.redis.delete(key)


def main() -> None:
    component_id = os.getenv("COMPONENT_ID", "controller-01")
    blackboard = create_blackboard()
    lock_enabled = env_bool("CONTROLLER_SINGLETON", True)
    lock_ttl = max(3, env_int("CONTROLLER_LOCK_TTL_SECONDS", 10))
    lock_owner = f"{component_id}@{host_name()}:{os.getpid()}"
    if lock_enabled and not acquire_controller_lock(blackboard, lock_owner, lock_ttl):
        current_owner = blackboard.redis.get(controller_lock_key(blackboard)) or "unknown"
        print(f"[controller] another controller is active ({current_owner}); {lock_owner} will exit")
        return

    base_config = base_simulation_config()
    config = read_runtime_config(blackboard, base_config)
    policy = create_policy(config)
    policy_key = config.policy
    controller = ControllerComponent(
        blackboard,
        policy,
        config.scan_radius,
        component_id=component_id,
    )
    interval = worker_interval()
    print(f"[controller] {component_id} connected to Redis prefix={blackboard.prefix}")

    try:
        while True:
            if lock_enabled and not refresh_controller_lock(blackboard, lock_owner, lock_ttl):
                print(f"[controller] lost controller lock; {lock_owner} will exit")
                return
            config = read_runtime_config(blackboard, base_config)
            controller.scan_radius = config.scan_radius
            if config.policy != policy_key:
                policy = create_policy(config)
                policy_key = config.policy
                controller.assignment_policy = policy
            if should_run(blackboard):
                with blackboard.batch():
                    controller.run_once()
                    heartbeat(blackboard, component_id, "CONTROLLER", "READY", None)
            else:
                with blackboard.batch():
                    heartbeat(blackboard, component_id, "CONTROLLER", "READY", None)
            time.sleep(interval)
    except KeyboardInterrupt:
        heartbeat(blackboard, component_id, "CONTROLLER", "OFFLINE", None)
        print(f"[controller] {component_id} stopped")
    finally:
        if lock_enabled:
            release_controller_lock(blackboard, lock_owner)


if __name__ == "__main__":
    main()
