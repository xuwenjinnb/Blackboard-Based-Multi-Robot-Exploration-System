from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .common import (
    create_blackboard,
    env_float,
    heartbeat,
    log_transient_redis_error,
    TRANSIENT_REDIS_ERRORS,
)


ChildMap = dict[str, subprocess.Popen]


def supervisor_interval() -> float:
    return max(0.2, env_float("ROBOT_SUPERVISOR_INTERVAL_SECONDS", 0.75))


def backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def configured_vehicle_ids(blackboard) -> list[str]:
    redis_client = getattr(blackboard, "redis", None)
    if redis_client is not None:
        return sorted(
            str(vehicle.get("vehicleId"))
            for vehicle in (
                blackboard._decode(value, {})
                for field, value in redis_client.hgetall(blackboard.key("vehicles")).items()
                if field != "__empty__"
            )
            if vehicle.get("vehicleId")
        )

    snapshot = blackboard.snapshot()
    return sorted(
        str(vehicle["vehicleId"])
        for vehicle in snapshot.get("vehicles", [])
        if vehicle.get("vehicleId")
    )


def start_robot_child(vehicle_id: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["VEHICLE_ID"] = vehicle_id
    for name in ("VEHICLE_X", "VEHICLE_Y", "VEHICLE_HEADING", "ROBOT_AUTO_REGISTER"):
        env.pop(name, None)

    child = subprocess.Popen(
        [sys.executable, "-u", "-m", "app.workers.robot_worker"],
        cwd=str(backend_dir()),
        env=env,
    )
    print(f"[robot-supervisor] started {vehicle_id} pid={child.pid}")
    return child


def stop_robot_child(vehicle_id: str, child: subprocess.Popen) -> None:
    if child.poll() is not None:
        print(f"[robot-supervisor] {vehicle_id} already exited code={child.returncode}")
        return

    print(f"[robot-supervisor] stopping {vehicle_id} pid={child.pid}")
    child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)


def reconcile_children(children: ChildMap, desired_ids: list[str]) -> None:
    desired = set(desired_ids)

    for vehicle_id, child in list(children.items()):
        if child.poll() is not None:
            print(f"[robot-supervisor] {vehicle_id} exited code={child.returncode}")
            del children[vehicle_id]

    for vehicle_id, child in list(children.items()):
        if vehicle_id not in desired:
            stop_robot_child(vehicle_id, child)
            del children[vehicle_id]

    for vehicle_id in desired_ids:
        if vehicle_id not in children:
            children[vehicle_id] = start_robot_child(vehicle_id)


def stop_all(children: ChildMap) -> None:
    for vehicle_id, child in list(children.items()):
        stop_robot_child(vehicle_id, child)
        del children[vehicle_id]


def main() -> None:
    blackboard = create_blackboard()
    children: ChildMap = {}
    interval = supervisor_interval()
    print(f"[robot-supervisor] connected to Redis prefix={blackboard.prefix}")

    try:
        while True:
            try:
                desired_ids = configured_vehicle_ids(blackboard)
                reconcile_children(children, desired_ids)
                heartbeat(
                    blackboard,
                    "robot-supervisor",
                    "ROBOT_SUPERVISOR",
                    "READY",
                    f"{len(children)}/{len(desired_ids)} vehicles",
                )
            except TRANSIENT_REDIS_ERRORS as exc:
                log_transient_redis_error("robot-supervisor", exc)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("[robot-supervisor] stopping children")
    finally:
        stop_all(children)
        heartbeat(blackboard, "robot-supervisor", "ROBOT_SUPERVISOR", "OFFLINE", None)


if __name__ == "__main__":
    main()
