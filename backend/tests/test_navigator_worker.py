from __future__ import annotations

from app.workers.navigator_worker import explicit_navigator_id, next_available_navigator_id


def test_next_available_navigator_id_skips_active_navigators():
    now = 10_000
    heartbeats = {
        "navigator-01": {
            "componentType": "NAVIGATOR",
            "status": "READY",
            "updatedAt": now,
        },
        "navigator-02": {
            "componentType": "NAVIGATOR",
            "status": "OFFLINE",
            "updatedAt": now,
        },
    }

    assert (
        next_available_navigator_id(
            heartbeats,
            current_time_ms=now,
            stale_after_ms=5_000,
        )
        == "navigator-02"
    )


def test_next_available_navigator_id_reuses_stale_navigator():
    now = 20_000
    heartbeats = {
        "navigator-01": {
            "componentType": "NAVIGATOR",
            "status": "READY",
            "updatedAt": now - 20_000,
        },
    }

    assert (
        next_available_navigator_id(
            heartbeats,
            current_time_ms=now,
            stale_after_ms=5_000,
        )
        == "navigator-01"
    )


def test_next_available_navigator_id_grows_from_active_processes():
    now = 30_000
    heartbeats = {
        "navigator-01": {
            "componentType": "NAVIGATOR",
            "status": "READY",
            "updatedAt": now,
        },
        "navigator-02": {
            "componentType": "NAVIGATOR",
            "status": "READY",
            "updatedAt": now,
        },
    }

    assert (
        next_available_navigator_id(
            heartbeats,
            current_time_ms=now,
            stale_after_ms=5_000,
        )
        == "navigator-03"
    )


def test_explicit_navigator_id_prefers_component_id(monkeypatch):
    monkeypatch.setenv("NAVIGATOR_ID", "navigator-08")
    monkeypatch.setenv("NAVIGATOR_IDS", "navigator-01,navigator-02")
    monkeypatch.setenv("COMPONENT_ID", "navigator-09")

    assert explicit_navigator_id() == "navigator-09"


def test_explicit_navigator_id_uses_first_legacy_id(monkeypatch):
    monkeypatch.delenv("NAVIGATOR_ID", raising=False)
    monkeypatch.delenv("COMPONENT_ID", raising=False)
    monkeypatch.setenv("NAVIGATOR_IDS", "navigator-01,navigator-02")

    assert explicit_navigator_id() == "navigator-01"
