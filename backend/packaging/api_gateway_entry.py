from __future__ import annotations

import argparse
import multiprocessing
import os

import uvicorn

from component_args import add_redis_arguments, apply_common_environment, ensure_backend_on_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the API gateway component.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--broadcast-interval", type=float, default=0.3)
    parser.add_argument(
        "--embedded-simulation",
        action="store_true",
        help="Run the old embedded simulation loop inside the API process.",
    )
    add_redis_arguments(parser)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_backend_on_path()
    apply_common_environment(args)
    os.environ["BROADCAST_INTERVAL_SECONDS"] = str(args.broadcast_interval)
    os.environ["RUN_EMBEDDED_SIMULATION"] = "true" if args.embedded_simulation else "false"

    from app.main import app

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
