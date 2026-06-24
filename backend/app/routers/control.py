from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request

from ..state import (
    blackboard,
    configure_navigator_algorithm,
    configure_policy,
    replay_store,
    runtime_state,
    simulation,
    snapshot_with_runtime,
)


router = APIRouter()


@router.post("/control/start")
async def control_start(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
) -> dict[str, Any]:
    payload = payload or {}
    if payload.get("policy"):
        configure_policy(str(payload["policy"]))
    if payload.get("navigatorAlgorithm"):
        configure_navigator_algorithm(str(payload["navigatorAlgorithm"]))
    simulation.ensure_demo_vehicles()
    blackboard.reset_perception_map_locked(reveal_obstacles=False)
    result = blackboard.set_system_status("RUNNING")
    snapshot = snapshot_with_runtime()
    replay_store.start(request.state.user["username"], runtime_state(), snapshot)
    return result


@router.post("/control/pause")
async def control_pause() -> dict[str, Any]:
    return blackboard.set_system_status("PAUSED")


@router.post("/control/resume")
async def control_resume() -> dict[str, Any]:
    return blackboard.set_system_status("RUNNING")


@router.post("/control/stop")
async def control_stop() -> dict[str, Any]:
    result = blackboard.set_system_status("STOPPED")
    replay_store.record(snapshot_with_runtime(), force=True)
    replay_store.finish("COMPLETED")
    return result


@router.post("/control/reset")
async def control_reset() -> dict[str, Any]:
    replay_store.record(snapshot_with_runtime(), force=True)
    replay_store.finish("RESET")
    result = blackboard.set_system_status("RESET")
    simulation.tick = 0
    simulation.movement_steps = 0
    simulation.ensure_demo_vehicles()
    return result
