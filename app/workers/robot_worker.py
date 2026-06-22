from __future__ import annotations

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


def publish_all_vehicle_heartbeats(blackboard) -> None:
    vehicles = blackboard.snapshot()["vehicles"]
    if not vehicles:
        heartbeat(blackboard, "robot-fleet", "ROBOT_MANAGER", "WAITING", "vehicles-not-configured")
        return
    for vehicle in vehicles:
        vehicle_id = vehicle["vehicleId"]
        status = "BUSY" if vehicle.get("status") in {"MOVING", "SCANNING"} else "READY"
        heartbeat(blackboard, vehicle_id, "ROBOT", status, vehicle.get("currentTaskId"))
    heartbeat(blackboard, "robot-fleet", "ROBOT_MANAGER", "READY", f"{len(vehicles)} vehicles")


def run_fleet_once(blackboard, robot: RobotComponent) -> None:
    with blackboard.batch():
        if not blackboard.snapshot()["vehicles"]:
            publish_all_vehicle_heartbeats(blackboard)
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


def main() -> None:
    blackboard = create_blackboard()
    base_config = base_simulation_config()
    config = read_runtime_config(blackboard, base_config)
    robot = RobotComponent(blackboard, config)
    interval = worker_interval()
    print(f"[robot-fleet] connected to Redis prefix={blackboard.prefix}")

    try:
        while True:
            config = read_runtime_config(blackboard, base_config)
            robot.config = config
            if should_run(blackboard):
                run_fleet_once(blackboard, robot)
            else:
                with blackboard.batch():
                    publish_all_vehicle_heartbeats(blackboard)
            time.sleep(interval)
    except KeyboardInterrupt:
        heartbeat(blackboard, "robot-fleet", "ROBOT_MANAGER", "OFFLINE", None)
        print("[robot-fleet] stopped")


if __name__ == "__main__":
    main()
