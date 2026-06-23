from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

import redis
from redis import RedisError

from .config import RedisConfig


T = TypeVar("T")
TRANSIENT_REDIS_ERRORS = (RedisError,)


class ResilientRedis(redis.Redis):
    """Redis client with a small retry window for transient disconnects."""

    def __init__(
        self,
        *args,
        retry_attempts: int = 3,
        retry_delay_seconds: float = 0.2,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.retry_attempts = max(1, retry_attempts)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)

    def execute_command(self, *args, **options):
        return _with_retry(
            lambda: super(ResilientRedis, self).execute_command(*args, **options),
            attempts=self.retry_attempts,
            delay_seconds=self.retry_delay_seconds,
        )


class RedisClientFactory:
    """Owns the Redis connection pool and short retry policy."""

    def __init__(self, config: RedisConfig) -> None:
        self.config = config
        self.pool = redis.ConnectionPool.from_url(
            config.url,
            decode_responses=True,
            max_connections=config.max_connections,
            socket_connect_timeout=config.socket_connect_timeout,
            socket_timeout=config.socket_timeout,
            health_check_interval=30,
        )

    def create_client(self, *, ping: bool = True) -> redis.Redis:
        client = ResilientRedis(
            connection_pool=self.pool,
            retry_attempts=self.config.retry_attempts,
            retry_delay_seconds=self.config.retry_delay_seconds,
        )
        if ping:
            self.execute(client.ping)
        return client

    def execute(self, operation: Callable[[], T]) -> T:
        return _with_retry(
            operation,
            attempts=self.config.retry_attempts,
            delay_seconds=self.config.retry_delay_seconds,
        )


def create_redis_client(config_or_url: RedisConfig | str, *, ping: bool = True) -> redis.Redis:
    config = (
        config_or_url
        if isinstance(config_or_url, RedisConfig)
        else RedisConfig(url=config_or_url)
    )
    return RedisClientFactory(config).create_client(ping=ping)


def log_transient_redis_error(component: str, exc: BaseException) -> None:
    print(f"[{component}] transient Redis error: {exc}. Will retry on next loop.")


def _with_retry(operation: Callable[[], T], *, attempts: int, delay_seconds: float) -> T:
    last_error: RedisError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except TRANSIENT_REDIS_ERRORS as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(delay_seconds)
    assert last_error is not None
    raise last_error
