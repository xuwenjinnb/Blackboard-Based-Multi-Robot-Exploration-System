from __future__ import annotations

import os
import time

from ..robot import RobotComponent
from .common import (
    base_simulation_config,
    create_blackboard,
    env_int,
    heartbeat,
    read_runtime_config,
    should_run,
    worker_interval,
)

HEARTBEAT_REFRESH_SECONDS = 2.0
_last_fleet_heartbeat_at = 0.0


def publish_all_vehicle_heartbeats(blackboard, *, force: bool = False) -> None:
    global _last_fleet_heartbeat_at
    current_time = time.monotonic()
    if not force and current_time - _last_fleet_heartbeat_at < HEARTBEAT_REFRESH_SECONDS:
        return
    vehicles = list(blackboard.vehicles.values())
    if not vehicles:
        heartbeat(blackboard, "robot-fleet", "ROBOT_MANAGER", "WAITING", "vehicles-not-configured")
        _last_fleet_heartbeat_at = current_time
        return
    for vehicle in vehicles:
        vehicle_id = vehicle["vehicleId"]
        status = "BUSY" if vehicle.get("status") in {"MOVING", "SCANNING"} else "READY"
        heartbeat(blackboard, vehicle_id, "ROBOT", status, vehicle.get("currentTaskId"))
    heartbeat(blackboard, "robot-fleet", "ROBOT_MANAGER", "READY", f"{len(vehicles)} vehicles")
    _last_fleet_heartbeat_at = current_time


def run_fleet_once(blackboard, robot: RobotComponent) -> None:
    with blackboard.batch():
        if not blackboard.vehicles:
            publish_all_vehicle_heartbeats(blackboard, force=True)
            return
        steps_per_tick = max(1, min(8, env_int("ROBOT_STEPS_PER_TICK", 1)))
        if robot.uses_low_level_mdp:
            for _ in range(steps_per_tick):
                if robot.run_low_level_mdp_once() <= 0:
                    break
        else:
            for _ in range(steps_per_tick):
                if robot.run_once() <= 0:
                    break
        publish_all_vehicle_heartbeats(blackboard)


def run_vehicle_once(blackboard, robot: RobotComponent, vehicle_id: str) -> None:
    with blackboard.batch():
        if not blackboard.vehicles:
            publish_all_vehicle_heartbeats(blackboard, force=True)
            return
        steps_per_tick = max(1, min(8, env_int("ROBOT_STEPS_PER_TICK", 1)))
        if robot.uses_low_level_mdp:
            for _ in range(steps_per_tick):
                if robot.run_low_level_mdp_vehicle_once(vehicle_id) <= 0:
                    break
        else:
            for _ in range(steps_per_tick):
                if robot.run_vehicle_once(vehicle_id) <= 0:
                    break
        publish_all_vehicle_heartbeats(blackboard)


def main() -> None:
    blackboard = create_blackboard()
    base_config = base_simulation_config()
    config = read_runtime_config(blackboard, base_config)
    robot = RobotComponent(blackboard, config)
    interval = worker_interval()
    vehicle_id = (os.getenv("VEHICLE_ID") or "").strip()
    worker_id = vehicle_id or "robot-fleet"
    print(f"[{worker_id}] connected to Redis prefix={blackboard.prefix}")

    try:
        while True:
            config = read_runtime_config(blackboard, base_config)
            robot.config = config
            if should_run(blackboard):
                if vehicle_id:
                    run_vehicle_once(blackboard, robot, vehicle_id)
                else:
                    run_fleet_once(blackboard, robot)
            else:
                with blackboard.batch():
                    publish_all_vehicle_heartbeats(blackboard)
            time.sleep(interval)
    except KeyboardInterrupt:
        heartbeat(blackboard, worker_id, "ROBOT_MANAGER", "OFFLINE", None)
        print(f"[{worker_id}] stopped")


if __name__ == "__main__":
    main()
