from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RedisConfig:
    url: str = "redis://127.0.0.1:6379/0"
    prefix: str = "inspection"
    reset_on_start: bool = False
    map_width: int = 50
    map_height: int = 50
    map_chunk_size: int = 10
    max_connections: int = 20
    socket_connect_timeout: float = 5.0
    socket_timeout: float = 5.0
    retry_attempts: int = 3
    retry_delay_seconds: float = 0.2


def redis_config_from_env() -> RedisConfig:
    return RedisConfig(
        url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        prefix=os.getenv("REDIS_PREFIX", "inspection"),
        reset_on_start=_env_bool("REDIS_RESET_ON_START", False),
        map_width=_env_int("INSPECTION_MAP_WIDTH", 50),
        map_height=_env_int("INSPECTION_MAP_HEIGHT", 50),
        map_chunk_size=_env_int("INSPECTION_MAP_CHUNK_SIZE", 10),
        max_connections=_env_int("REDIS_MAX_CONNECTIONS", 20),
        socket_connect_timeout=_env_float("REDIS_CONNECT_TIMEOUT_SECONDS", 5.0),
        socket_timeout=_env_float("REDIS_SOCKET_TIMEOUT_SECONDS", 5.0),
        retry_attempts=max(1, _env_int("REDIS_RETRY_ATTEMPTS", 3)),
        retry_delay_seconds=max(0.0, _env_float("REDIS_RETRY_DELAY_SECONDS", 0.2)),
    )


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default
