from __future__ import annotations

import os
import uuid

import pytest

redis = pytest.importorskip("redis")

from app.redis import AuthStore, ReplayStore, ROLE_ANALYST, ROLE_OPERATOR


REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/15")


@pytest.fixture()
def redis_store():
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.RedisError as exc:
        pytest.skip(f"Redis is unavailable: {exc}")
    prefix = f"inspection:test:{uuid.uuid4().hex}"
    try:
        yield client, prefix
    finally:
        for key in client.scan_iter(match=f"{prefix}:*"):
            client.delete(key)


def test_auth_store_seeds_admin_and_manages_roles(redis_store):
    client, prefix = redis_store
    store = AuthStore(client, prefix)

    admin_login = store.login("huadian", "123456")
    assert admin_login is not None
    assert admin_login["user"]["role"] == "admin"

    operator = store.create_user("operator01", "123456", ROLE_OPERATOR, "运行员")
    analyst = store.create_user("analyst01", "123456", ROLE_ANALYST, "分析员")
    assert operator["role"] == ROLE_OPERATOR
    assert analyst["role"] == ROLE_ANALYST

    store.update_user("analyst01", enabled=False)
    assert store.login("analyst01", "123456") is None


def test_replay_store_round_trips_compressed_text_frames(redis_store):
    client, prefix = redis_store
    store = ReplayStore(client, prefix)
    snapshot = {
        "map": {
            "width": 2,
            "height": 1,
            "cells": [
                {"x": 0, "y": 0, "state": "VISITED"},
                {"x": 1, "y": 0, "state": "UNKNOWN"},
            ],
        },
        "vehicles": [{"vehicleId": "car-01"}],
        "runtime": {"movementSteps": 3},
    }

    replay_id = store.start(
        "operator01",
        {"policy": "nearest", "navigatorAlgorithm": "astar"},
        snapshot,
    )
    store.record(snapshot, force=True)
    store.finish()

    replay = store.get_replay(replay_id)
    assert replay is not None
    assert replay["meta"]["operator"] == "operator01"
    assert replay["meta"]["lastCoverage"] == 50.0
    assert len(replay["frames"]) == 2
    assert replay["frames"][0]["snapshot"]["vehicles"][0]["vehicleId"] == "car-01"


def test_replay_store_compacts_and_samples_frames(redis_store):
    client, prefix = redis_store
    store = ReplayStore(client, prefix)
    snapshot = {
        "map": {
            "width": 2,
            "height": 1,
            "cells": [{"x": 0, "y": 0, "state": "VISITED"}],
            "chunks": [{"duplicate": "map data"}],
        },
        "vehicles": [],
        "events": [{"eventId": index} for index in range(100)],
        "runtime": {},
    }
    replay_id = store.start("operator01", {}, snapshot)
    for _ in range(9):
        store.record(snapshot, force=True)
    store.finish()

    replay = store.get_replay(replay_id, max_frames=4)
    assert replay is not None
    assert len(replay["frames"]) == 4
    assert replay["meta"]["sampled"] is True
    assert "chunks" not in replay["frames"][0]["snapshot"]["map"]
    assert len(replay["frames"][0]["snapshot"]["events"]) == 20
    assert replay["frames"][0]["snapshot"]["dataCounts"]["events"] == 100
    assert replay["frames"][0]["snapshot"]["map"]["cellStates"] == "VU"
    assert "cells" not in replay["frames"][0]["snapshot"]["map"]
