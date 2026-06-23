from __future__ import annotations

import copy
import os
import uuid

import pytest

redis = pytest.importorskip("redis")

from app.redis import RedisBlackboard


REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/15")


@pytest.fixture()
def redis_blackboard():
    try:
        client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        client.ping()
    except redis.RedisError as exc:
        pytest.skip(f"Redis is unavailable: {exc}")

    prefix = f"inspection:test:{uuid.uuid4().hex}"
    blackboard = RedisBlackboard(
        REDIS_URL,
        prefix=prefix,
        width=8,
        height=6,
        reset_on_start=True,
    )
    try:
        yield blackboard
    finally:
        blackboard.delete_namespace()


def test_redis_blackboard_persists_all_state_groups(redis_blackboard):
    blackboard = redis_blackboard
    vehicle = blackboard.register_vehicle(
        "car-01",
        {"position": {"x": 1, "y": 1}, "heading": 0},
    )
    blackboard.upload_map_patch(
        {
            "vehicleId": "car-01",
            "cells": [{"x": 1, "y": 1, "state": "VISITED"}],
        }
    )
    frontier = blackboard.save_frontier(
        {
            "position": {"x": 2, "y": 1},
            "unknownGain": 3,
            "discoveredBy": "car-01",
        }
    )
    task = blackboard.create_task_for_frontier(vehicle["vehicleId"], frontier)
    request = blackboard.create_navigation_request(task)
    claim = blackboard.claim_navigation_request("navigator-01")
    blackboard.write_navigation_plan(
        {
            "requestId": request["requestId"],
            "taskId": task["taskId"],
            "vehicleId": vehicle["vehicleId"],
            "createdBy": "navigator-01",
            "status": "SUCCESS",
            "path": [],
        }
    )
    blackboard.set_system_status("RUNNING")

    snapshot = blackboard.snapshot()
    assert snapshot["map"]["cells"]
    assert snapshot["map"]["chunks"]
    assert snapshot["vehicles"]
    assert snapshot["frontiers"]
    assert snapshot["tasks"]
    assert snapshot["navigationRequests"]
    assert snapshot["navigationPlans"]
    assert snapshot["heartbeats"]
    assert snapshot["events"]
    assert snapshot["systemStatus"] == "RUNNING"
    assert claim["claimed"] is True

    expected_keys = {
        blackboard.key("map:meta"),
        blackboard.key("map:chunks"),
        blackboard.key("vehicles"),
        blackboard.key("frontiers"),
        blackboard.key("tasks"),
        blackboard.key("navigation_requests"),
        blackboard.key("navigation_plans"),
        blackboard.key("heartbeats"),
        blackboard.key("events"),
        blackboard.key("system"),
    }
    stored_keys = set(blackboard.redis.scan_iter(match=f"{blackboard.prefix}:*"))
    assert expected_keys <= stored_keys
    assert blackboard.key("map:cells") not in stored_keys


def test_redis_blackboard_survives_new_instance(redis_blackboard):
    blackboard = redis_blackboard
    blackboard.register_vehicle(
        "car-02",
        {"position": {"x": 3, "y": 2}, "heading": 90},
    )
    blackboard.set_system_status("PAUSED")

    restored = RedisBlackboard(
        REDIS_URL,
        prefix=blackboard.prefix,
        width=8,
        height=6,
    )
    snapshot = restored.snapshot()

    assert snapshot["systemStatus"] == "PAUSED"
    assert snapshot["vehicles"][0]["vehicleId"] == "car-02"
    assert snapshot["map"]["chunks"]


def test_reset_on_start_removes_stale_runtime_hash_fields(redis_blackboard):
    blackboard = redis_blackboard
    vehicle = blackboard.register_vehicle(
        "car-01",
        {"position": {"x": 1, "y": 1}, "heading": 0},
    )
    frontier = blackboard.save_frontier(
        {
            "position": {"x": 2, "y": 1},
            "unknownGain": 3,
            "discoveredBy": vehicle["vehicleId"],
        }
    )
    task = blackboard.create_task_for_frontier(vehicle["vehicleId"], frontier)
    request = blackboard.create_navigation_request(task)
    blackboard.write_navigation_plan(
        {
            "requestId": request["requestId"],
            "taskId": task["taskId"],
            "vehicleId": vehicle["vehicleId"],
            "createdBy": "navigator-01",
            "status": "SUCCESS",
            "path": [],
        }
    )

    restored = RedisBlackboard(
        REDIS_URL,
        prefix=blackboard.prefix,
        width=8,
        height=6,
        reset_on_start=True,
    )
    snapshot = restored.snapshot()

    assert snapshot["vehicles"] == []
    assert snapshot["frontiers"] == []
    assert snapshot["tasks"] == []
    assert snapshot["navigationRequests"] == []
    assert snapshot["navigationPlans"] == []
    for redis_name in RedisBlackboard.COLLECTIONS.values():
        fields = restored.redis.hgetall(restored.key(redis_name))
        assert set(fields) <= {"__empty__"}


def test_snapshot_closes_stale_out_of_bounds_frontier(redis_blackboard):
    blackboard = redis_blackboard
    blackboard.redis.hset(
        blackboard.key("frontiers"),
        "frontier-stale",
        RedisBlackboard._encode(
            {
                "frontierId": "frontier-stale",
                "position": {"x": 9, "y": 2},
                "unknownGain": 5,
                "discoveredBy": "car-01",
                "status": "OPEN",
                "timestamp": 1,
            }
        ),
    )

    restored = RedisBlackboard(
        REDIS_URL,
        prefix=blackboard.prefix,
        width=8,
        height=6,
    )
    snapshot = restored.snapshot()

    assert snapshot["frontiers"][0]["frontierId"] == "frontier-stale"
    assert snapshot["frontiers"][0]["status"] == "CLOSED"
    assert snapshot["frontiers"][0]["unknownGain"] == 0
    assert restored.open_frontiers() == []


def test_redis_blackboard_repairs_incomplete_persisted_chunks(redis_blackboard):
    blackboard = redis_blackboard
    chunk = copy.deepcopy(blackboard.snapshot()["map"]["chunks"][0])
    chunk["cells"] = [
        cell
        for cell in chunk["cells"]
        if (int(cell["x"]), int(cell["y"])) != (0, 0)
    ]
    blackboard.redis.hset(
        blackboard.key("map:chunks"),
        chunk["chunkId"],
        RedisBlackboard._encode(chunk),
    )

    restored = RedisBlackboard(
        REDIS_URL,
        prefix=blackboard.prefix,
        width=8,
        height=6,
    )
    snapshot = restored.snapshot()
    cell_map = {
        (int(cell["x"]), int(cell["y"])): cell
        for cell in snapshot["map"]["cells"]
    }

    assert len(snapshot["map"]["cells"]) == 48
    assert len(snapshot["map"]["chunks"][0]["cells"]) == 48
    assert cell_map[(0, 0)]["state"] == "UNKNOWN"


def test_load_state_filters_cells_outside_current_map(redis_blackboard):
    blackboard = redis_blackboard
    meta = blackboard.redis.hgetall(blackboard.key("map:meta"))
    meta.update({"width": "8", "height": "6", "chunkSize": "4"})
    blackboard.redis.hset(blackboard.key("map:meta"), mapping=meta)

    chunk = copy.deepcopy(blackboard.snapshot()["map"]["chunks"][0])
    chunk["cells"].append(
        {
            "x": 8,
            "y": 2,
            "state": "FREE",
            "confidence": 1.0,
            "updatedBy": "stale-worker",
            "updatedAt": 1,
        }
    )
    blackboard.redis.hset(
        blackboard.key("map:chunks"),
        chunk["chunkId"],
        RedisBlackboard._encode(chunk),
    )

    restored = RedisBlackboard(
        REDIS_URL,
        prefix=blackboard.prefix,
        width=50,
        height=50,
    )
    with restored.batch():
        snapshot = restored.snapshot_view()

    assert snapshot["map"]["width"] == 8
    assert snapshot["map"]["height"] == 6
    assert all(
        0 <= int(cell["x"]) < 8 and 0 <= int(cell["y"]) < 6
        for cell in snapshot["map"]["cells"]
    )


def test_navigation_request_claim_is_exclusive(redis_blackboard):
    blackboard = redis_blackboard
    blackboard.register_vehicle(
        "car-01",
        {"position": {"x": 1, "y": 1}, "heading": 0},
    )
    frontier = blackboard.save_frontier(
        {
            "position": {"x": 2, "y": 1},
            "unknownGain": 2,
            "discoveredBy": "car-01",
        }
    )
    task = blackboard.create_task_for_frontier("car-01", frontier)
    blackboard.create_navigation_request(task)

    first = blackboard.claim_navigation_request("navigator-01")
    second = blackboard.claim_navigation_request("navigator-02")

    assert first["claimed"] is True
    assert second["claimed"] is False


def test_direct_ids_repair_stale_counters_before_writing(redis_blackboard):
    blackboard = redis_blackboard
    blackboard.register_vehicle(
        "car-01",
        {"position": {"x": 1, "y": 1}, "heading": 0},
    )
    blackboard.register_vehicle(
        "car-02",
        {"position": {"x": 3, "y": 1}, "heading": 0},
    )
    first_frontier = blackboard.save_frontier(
        {
            "position": {"x": 2, "y": 1},
            "unknownGain": 2,
            "discoveredBy": "car-01",
        }
    )
    first_task = blackboard.create_task_for_frontier("car-01", first_frontier)
    first_request = blackboard.create_navigation_request(first_task)

    blackboard.redis.hset(blackboard.key("counters"), mapping={"task": 0, "request": 0})

    second_frontier = blackboard.save_frontier(
        {
            "position": {"x": 4, "y": 1},
            "unknownGain": 2,
            "discoveredBy": "car-02",
        }
    )
    second_task = blackboard.create_task_for_frontier("car-02", second_frontier)
    second_request = blackboard.create_navigation_request(second_task)

    assert second_task["taskId"] != first_task["taskId"]
    assert second_request["requestId"] != first_request["requestId"]
    snapshot = blackboard.snapshot()
    assert {task["taskId"] for task in snapshot["tasks"]} >= {
        first_task["taskId"],
        second_task["taskId"],
    }
    assert {request["requestId"] for request in snapshot["navigationRequests"]} >= {
        first_request["requestId"],
        second_request["requestId"],
    }
