from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from ..state import (
    blackboard,
    configure_navigator_algorithm,
    configure_policy,
    embedded_simulation_enabled,
    redis_config,
    runtime_state,
    simulation,
    snapshot_with_runtime,
)


router = APIRouter()


@router.get("/state")
async def get_state(
    map_version: int | None = Query(default=None, alias="mapVersion"),
    map_generation: int | None = Query(default=None, alias="mapGeneration"),
) -> dict[str, Any]:
    return await asyncio.to_thread(snapshot_with_runtime, map_version, map_generation)


@router.get("/runtime")
async def get_runtime() -> dict[str, Any]:
    return runtime_state()


@router.get("/health/redis")
async def redis_health() -> dict[str, Any]:
    return {
        "ok": blackboard.ping(),
        "url": redis_config.url,
        "prefix": redis_config.prefix,
        "deploymentRole": os.getenv("DEPLOYMENT_ROLE", "standalone"),
        "embeddedSimulation": embedded_simulation_enabled,
        "nodeId": os.getenv("NODE_ID", "computer-a"),
    }


@router.post("/runtime/policy")
async def set_runtime_policy(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    if blackboard.system_status == "RUNNING":
        raise HTTPException(status_code=409, detail="pause or stop the simulation before changing policy")
    payload = payload or {}
    return configure_policy(str(payload.get("policy", "nearest")))


@router.post("/runtime/navigator")
async def set_runtime_navigator(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    if blackboard.system_status == "RUNNING":
        raise HTTPException(status_code=409, detail="pause or stop the simulation before changing navigator")
    payload = payload or {}
    return configure_navigator_algorithm(str(payload.get("navigatorAlgorithm", "baseline")))


@router.post("/runtime/vehicles")
async def set_runtime_vehicles(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    if blackboard.system_status == "RUNNING":
        raise HTTPException(status_code=409, detail="pause or stop the simulation before changing vehicles")
    payload = payload or {}
    try:
        deployment = simulation.configure_vehicle_deployment(
            count=int(payload.get("count", 8)),
            mode=str(payload.get("mode", "manual")),
            positions=list(payload.get("positions") or []),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deployment": deployment, "snapshot": snapshot_with_runtime()}


@router.post("/runtime/map")
async def set_runtime_map(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    if blackboard.system_status in {"RUNNING", "PAUSED"}:
        raise HTTPException(status_code=409, detail="stop the simulation before changing map size")
    payload = payload or {}
    try:
        layout = simulation.configure_map(
            width=int(payload.get("width", blackboard.width)),
            height=int(payload.get("height", blackboard.height)),
            chunk_size=int(payload["chunkSize"]) if payload.get("chunkSize") is not None else None,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"map": layout, "deployment": simulation.vehicle_deployment, "snapshot": snapshot_with_runtime()}


@router.post("/runtime/obstacles")
async def set_runtime_obstacles(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    if blackboard.system_status in {"RUNNING", "PAUSED"}:
        raise HTTPException(status_code=409, detail="stop the simulation before changing obstacles")
    payload = payload or {}
    try:
        obstacle_count = payload.get("count")
        layout = simulation.configure_obstacles(
            mode=str(payload.get("mode", "manual")),
            obstacles=list(payload.get("obstacles") or []),
            density=float(payload.get("density", 0.18)),
            seed=payload.get("seed"),
            count=int(obstacle_count) if obstacle_count is not None else None,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"obstacles": layout, "deployment": simulation.vehicle_deployment, "snapshot": snapshot_with_runtime()}


@router.post("/runtime/obstacles/cell")
async def set_runtime_obstacle_cell(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    if blackboard.system_status in {"RUNNING", "PAUSED"}:
        raise HTTPException(status_code=409, detail="stop the simulation before changing obstacles")
    payload = payload or {}
    try:
        result = simulation.set_obstacle_at(
            int(payload["x"]),
            int(payload["y"]),
            payload.get("blocked"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"missing field: {exc.args[0]}") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"obstacle": result, "deployment": simulation.vehicle_deployment, "snapshot": snapshot_with_runtime()}


@router.post("/runtime/obstacles/cells")
async def set_runtime_obstacle_cells(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    if blackboard.system_status in {"RUNNING", "PAUSED"}:
        raise HTTPException(status_code=409, detail="stop the simulation before changing obstacles")
    payload = payload or {}
    try:
        cells = list(payload.get("cells") or [])
        result = simulation.set_obstacles_at(cells)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"obstacles": result, "deployment": simulation.vehicle_deployment, "snapshot": snapshot_with_runtime()}
