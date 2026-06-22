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
    parser = argparse.ArgumentParser(description="Run the robot process supervisor component.")
    parser.add_argument("--supervisor-interval", type=float, default=0.75)
    parser.add_argument("--steps-per-tick", type=int, default=1)
    add_worker_interval_argument(parser)
    add_redis_arguments(parser)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_backend_on_path()
    apply_common_environment(args)
    os.environ["ROBOT_SUPERVISOR_INTERVAL_SECONDS"] = str(args.supervisor_interval)
    os.environ["ROBOT_STEPS_PER_TICK"] = str(args.steps_per_tick)
    os.environ.pop("VEHICLE_ID", None)

    from app.workers.robot_supervisor import main as run_supervisor

    run_supervisor()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
