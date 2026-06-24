from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .redis import ROLE_OPERATOR, coverage, now_ms
from .state import (
    auth_store,
    blackboard,
    broadcast_interval,
    configure_navigator_algorithm,
    configure_policy,
    replay_store,
    runtime_state,
    simulation,
    snapshot_map_cursor,
    snapshot_with_runtime,
)


websockets: set[WebSocket] = set()
websocket_map_versions: dict[WebSocket, tuple[int, int] | None] = {}


def register_websocket(app: FastAPI) -> None:
    app.add_api_websocket_route("/ws", websocket_endpoint)


async def websocket_endpoint(websocket: WebSocket) -> None:
    user = auth_store.get_session(websocket.query_params.get("token"))
    if not user or user["role"] != ROLE_OPERATOR:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    websockets.add(websocket)
    initial_snapshot = snapshot_with_runtime()
    websocket_map_versions[websocket] = snapshot_map_cursor(initial_snapshot)
    await websocket.send_json({"type": "STATE_SNAPSHOT", "payload": initial_snapshot})
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "CONTROL":
                await apply_ws_control(message)
    except WebSocketDisconnect:
        websockets.discard(websocket)
        websocket_map_versions.pop(websocket, None)


async def apply_ws_control(message: dict[str, Any]) -> None:
    action = message.get("action")
    if action == "start":
        if message.get("policy"):
            configure_policy(str(message["policy"]))
        if message.get("navigatorAlgorithm"):
            configure_navigator_algorithm(str(message["navigatorAlgorithm"]))
        simulation.ensure_demo_vehicles()
        blackboard.reset_perception_map_locked(reveal_obstacles=False)
        blackboard.set_system_status("RUNNING")
        replay_store.start("websocket", runtime_state(), snapshot_with_runtime())
    elif action == "pause":
        blackboard.set_system_status("PAUSED")
    elif action == "resume":
        blackboard.set_system_status("RUNNING")
    elif action == "stop":
        blackboard.set_system_status("STOPPED")
        replay_store.record(snapshot_with_runtime(), force=True)
        replay_store.finish("COMPLETED")
    elif action == "reset":
        replay_store.record(snapshot_with_runtime(), force=True)
        replay_store.finish("RESET")
        blackboard.set_system_status("RESET")
        simulation.tick = 0
        simulation.movement_steps = 0
        simulation.ensure_demo_vehicles()


async def broadcast_loop() -> None:
    while True:
        system_status = blackboard.system_status
        if replay_store.should_record() and system_status == "RUNNING":
            replay_snapshot = await asyncio.to_thread(snapshot_with_runtime)
            replay_store.record(replay_snapshot)
            if coverage(replay_snapshot) >= 100:
                blackboard.set_system_status("PAUSED")
                replay_store.finish("COMPLETED")
        if websockets:
            stale: list[WebSocket] = []
            for websocket in list(websockets):
                try:
                    cursor = websocket_map_versions.get(websocket)
                    snapshot = await asyncio.to_thread(
                        snapshot_with_runtime,
                        cursor[0] if cursor else None,
                        cursor[1] if cursor else None,
                    )
                    next_cursor = snapshot_map_cursor(snapshot)
                    if next_cursor is not None:
                        websocket_map_versions[websocket] = next_cursor
                    message = {"type": "STATE_SNAPSHOT", "payload": snapshot, "sentAt": now_ms()}
                    await websocket.send_json(message)
                except Exception:
                    stale.append(websocket)
            for websocket in stale:
                websockets.discard(websocket)
                websocket_map_versions.pop(websocket, None)
        await asyncio.sleep(broadcast_interval)
