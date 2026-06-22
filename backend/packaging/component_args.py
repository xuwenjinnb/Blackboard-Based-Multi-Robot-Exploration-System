from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def ensure_backend_on_path() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))


def add_redis_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--redis-url", default=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
    parser.add_argument("--redis-prefix", default=os.getenv("REDIS_PREFIX", "inspection"))


def add_worker_interval_argument(parser: argparse.ArgumentParser, default: float = 0.3) -> None:
    parser.add_argument("--worker-interval", type=float, default=default)


def apply_common_environment(args: argparse.Namespace) -> None:
    os.environ["PYTHONUNBUFFERED"] = "1"
    if getattr(args, "redis_url", None):
        os.environ["REDIS_URL"] = args.redis_url
    if getattr(args, "redis_prefix", None):
        os.environ["REDIS_PREFIX"] = args.redis_prefix
    if hasattr(args, "worker_interval"):
        os.environ["WORKER_INTERVAL_SECONDS"] = str(args.worker_interval)
