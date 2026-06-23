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
    parser = argparse.ArgumentParser(description="Run one navigator worker process.")
    parser.add_argument("--component-id", default="")
    parser.add_argument("--batches-per-tick", type=int, default=3)
    add_worker_interval_argument(parser)
    add_redis_arguments(parser)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_backend_on_path()
    apply_common_environment(args)
    os.environ["NAVIGATOR_BATCHES_PER_TICK"] = str(args.batches_per_tick)
    os.environ.pop("NAVIGATOR_ID", None)
    os.environ.pop("NAVIGATOR_IDS", None)
    if args.component_id.strip():
        os.environ["COMPONENT_ID"] = args.component_id
    else:
        os.environ.pop("COMPONENT_ID", None)

    from app.workers.navigator_worker import main as run_worker

    run_worker()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
