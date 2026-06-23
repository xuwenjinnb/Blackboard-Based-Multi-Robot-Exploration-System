from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..state import blackboard


router = APIRouter()


@router.post("/robot/register")
async def register_robot(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.register_vehicle(payload["vehicleId"], payload["pose"])


@router.post("/robot/state")
async def update_robot_state(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.update_vehicle_state(payload)


@router.post("/robot/map-patch")
async def upload_map_patch(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.upload_map_patch(payload)


@router.post("/frontiers")
async def upload_frontier(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.save_frontier(payload)


@router.post("/navigation-requests")
async def create_navigation_request(payload: dict[str, Any]) -> dict[str, Any]:
    task = blackboard.get_task(payload["taskId"])
    if task:
        return blackboard.create_navigation_request(task, payload.get("priority", 5))
    return blackboard.save_navigation_request(payload)


@router.post("/navigation-requests/claim")
async def claim_navigation_request(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.claim_navigation_request(payload["navigatorId"])


@router.post("/navigation-plans")
async def write_navigation_plan(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.write_navigation_plan(payload)


@router.get("/vehicle-task")
async def get_vehicle_task(vehicleId: str) -> dict[str, Any] | None:
    return blackboard.get_vehicle_task(vehicleId)


@router.post("/heartbeat")
async def heartbeat(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.update_heartbeat(
        payload["componentId"],
        payload["componentType"],
        payload.get("status", "READY"),
        payload.get("currentWorkId"),
        payload.get("host"),
        payload.get("pid"),
    )
