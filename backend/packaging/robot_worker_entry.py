from __future__ import annotations

import argparse
import multiprocessing
import os

from component_args import (
    add_redis_arguments,
    add_worker_interval_argument,
    apply_common_environment,
    ensure_backend_on_path,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the robot fleet execution worker component.")
    parser.add_argument("--vehicle-id", default="")
    parser.add_argument("--steps-per-tick", type=int, default=1)
    add_worker_interval_argument(parser)
    add_redis_arguments(parser)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_backend_on_path()
    apply_common_environment(args)
    os.environ["ROBOT_STEPS_PER_TICK"] = str(args.steps_per_tick)
    if args.vehicle_id.strip():
        os.environ["VEHICLE_ID"] = args.vehicle_id.strip()
    else:
        os.environ.pop("VEHICLE_ID", None)
    for name in ("VEHICLE_X", "VEHICLE_Y", "VEHICLE_HEADING", "ROBOT_AUTO_REGISTER"):
        os.environ.pop(name, None)

    from app.workers.robot_worker import main as run_worker

    run_worker()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
