from __future__ import annotations

import argparse
import ctypes
import multiprocessing
import os
import sys

from component_args import (
    add_redis_arguments,
    add_worker_interval_argument,
    apply_common_environment,
    ensure_backend_on_path,
)


ERROR_ALREADY_EXISTS = 183
_mutex_handle: int | None = None


def acquire_os_singleton() -> None:
    global _mutex_handle
    if os.name != "nt":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, "Local\\MultiCarInspectionControllerWorker")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    _mutex_handle = handle
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        print("[controller] another controller_worker.exe instance is already running; exiting")
        sys.exit(0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the singleton controller worker component.")
    parser.add_argument("--component-id", default="controller-01")
    parser.add_argument("--controller-singleton", choices=("true", "false"), default="true")
    parser.add_argument("--controller-lock-ttl", type=int, default=60)
    add_worker_interval_argument(parser)
    add_redis_arguments(parser)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    acquire_os_singleton()
    ensure_backend_on_path()
    apply_common_environment(args)
    os.environ["COMPONENT_ID"] = args.component_id
    os.environ["CONTROLLER_SINGLETON"] = args.controller_singleton
    os.environ["CONTROLLER_LOCK_TTL_SECONDS"] = str(args.controller_lock_ttl)

    from app.workers.controller_worker import main as run_worker

    run_worker()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
