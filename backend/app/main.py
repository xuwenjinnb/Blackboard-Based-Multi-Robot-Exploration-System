from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .redis import now_ms
from .config import simulation_config_from_env
from .controller.policies import create_assignment_policy
from .redis import (
    AuthStore,
    RedisBlackboard,
    ReplayStore,
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_OPERATOR,
    coverage,
    redis_config_from_env,
)
from .simulation import SimulationEngine
from .workers.common import env_bool, env_float, persist_runtime_config


BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"
PATHFINDING_FRONTEND_DIR = FRONTEND_DIR / "Pathfinding-Visualizer-ThreeJS-master"
PATHFINDING_DIST_DIR = PATHFINDING_FRONTEND_DIR / "dist"

DEFAULT_CORS_ORIGINS = [
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "http://127.0.0.1:8081",
    "http://localhost:8081",
]

PRIVATE_NETWORK_ORIGIN_REGEX = (
    r"https?://("
    r"localhost|127\.0\.0\.1|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?"
)


def cors_origins_from_env() -> list[str]:
    value = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if not value:
        return DEFAULT_CORS_ORIGINS
    return [origin.strip() for origin in value.split(",") if origin.strip()]


app = FastAPI(title="Multi-car Blackboard Simulation")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_from_env(),
    allow_origin_regex=PRIVATE_NETWORK_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
redis_config = redis_config_from_env()
blackboard = RedisBlackboard(
    redis_config,
    prefix=redis_config.prefix,
    width=redis_config.map_width,
    height=redis_config.map_height,
    chunk_size=redis_config.map_chunk_size,
    reset_on_start=redis_config.reset_on_start,
)
auth_store = AuthStore(blackboard.redis, redis_config.prefix)
replay_store = ReplayStore(blackboard.redis, redis_config.prefix)
simulation_config = simulation_config_from_env()
startup_policy = simulation_config.policy
assignment_policy = create_assignment_policy(startup_policy)
simulation = SimulationEngine(blackboard, assignment_policy=assignment_policy, config=simulation_config)
embedded_simulation_enabled = env_bool("RUN_EMBEDDED_SIMULATION", True)
broadcast_interval = max(0.15, env_float("BROADCAST_INTERVAL_SECONDS", 0.3))
persist_runtime_config(blackboard, simulation.config)
websockets: set[WebSocket] = set()
websocket_map_versions: dict[WebSocket, tuple[int, int] | None] = {}

PUBLIC_PATHS = {"/", "/pathfinding", "/dashboard", "/auth/login", "/health/redis"}
INTERNAL_PREFIXES = (
    "/robot/",
    "/frontiers",
    "/navigation-requests",
    "/navigation-plans",
    "/vehicle-task",
    "/heartbeat",
)


def bearer_token(request: Request) -> str | None:
    value = request.headers.get("Authorization", "")
    return value[7:].strip() if value.startswith("Bearer ") else None


@app.middleware("http")
async def authorize_request(request: Request, call_next):
    path = request.url.path
    if (
        path in PUBLIC_PATHS
        or path.startswith("/static/")
        or path.startswith("/Pathfinding-Visualizer-ThreeJS/")
        or path.startswith(INTERNAL_PREFIXES)
    ):
        return await call_next(request)

    user = auth_store.get_session(bearer_token(request))
    if not user:
        return JSONResponse(status_code=401, content={"detail": "请先登录"})
    request.state.user = user

    if path.startswith("/admin/") and user["role"] != ROLE_ADMIN:
        return JSONResponse(status_code=403, content={"detail": "仅超级管理员可访问"})
    if path.startswith("/replays"):
        if user["role"] not in {ROLE_ADMIN, ROLE_ANALYST}:
            return JSONResponse(status_code=403, content={"detail": "仅分析员可访问回放"})
    elif path.startswith(("/control/", "/runtime/", "/state", "/ws")):
        if user["role"] != ROLE_OPERATOR:
            return JSONResponse(status_code=403, content={"detail": "仅系统运行员可操作仿真"})
    return await call_next(request)

POLICY_OPTIONS = [
    {
        "id": "nearest",
        "name": "Nearest reachable frontier",
        "summary": "Use A* to verify reachability, then choose the nearest frontier.",
    },
    {
        "id": "greedy",
        "name": "Greedy information gain",
        "summary": "Prefer frontiers with higher unknown-cell gain and lower travel cost.",
    },
    {
        "id": "low_mdp",
        "name": "Low-level MDP",
        "summary": "Move by local value iteration and use a repulsion field to reduce clustering.",
    },
]

NAVIGATOR_OPTIONS = [
    {
        "id": "baseline",
        "name": "Baseline",
        "summary": "Plan each navigation request with A* or space-time A* reservations.",
    },
    {
        "id": "cbs",
        "name": "CBS",
        "summary": "Batch pending requests, detect path conflicts, and replan with constraints.",
    },
]

def normalize_policy(policy: str | None) -> str:
    key = (policy or "nearest").strip().lower()
    aliases = {
        "nearest-reachable": "nearest",
        "nearest-reachable-frontier": "nearest",
        "greedy-frontier": "greedy",
        "gain": "greedy",
        "low-mdp": "low_mdp",
        "low-level-mdp": "low_mdp",
        "low_level_mdp": "low_mdp",
    }
    key = aliases.get(key, key)
    valid = {item["id"] for item in POLICY_OPTIONS}
    if key not in valid:
        raise HTTPException(status_code=400, detail=f"unknown policy: {policy}")
    return key


def normalize_navigator_algorithm(algorithm: str | None) -> str:
    key = (algorithm or "baseline").strip().lower()
    aliases = {
        "base": "baseline",
        "st_astar": "baseline",
        "st-astar": "baseline",
        "reservation": "baseline",
        "reservations": "baseline",
        "conflict-based-search": "cbs",
    }
    key = aliases.get(key, key)
    valid = {item["id"] for item in NAVIGATOR_OPTIONS}
    if key not in valid:
        raise HTTPException(status_code=400, detail=f"unknown navigator algorithm: {algorithm}")
    return key


def configure_policy(policy: str) -> dict[str, Any]:
    normalized = normalize_policy(policy)
    try:
        assignment_policy = create_assignment_policy(normalized)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    simulation.config = replace(simulation.config, policy=normalized)
    simulation.assignment_policy = assignment_policy
    persist_runtime_config(blackboard, simulation.config)
    blackboard.add_event("controller", "POLICY_CHANGED", f"Policy switched to {normalized}")
    return runtime_state()


def configure_navigator_algorithm(algorithm: str) -> dict[str, Any]:
    normalized = normalize_navigator_algorithm(algorithm)
    simulation.config = replace(simulation.config, navigator_algorithm=normalized)
    persist_runtime_config(blackboard, simulation.config)
    blackboard.add_event("navigator", "NAVIGATOR_CHANGED", f"Navigator algorithm switched to {normalized}")
    return runtime_state()


def active_navigator_heartbeats() -> list[dict[str, Any]]:
    stale_after_ms = int(max(1.0, env_float("NAVIGATOR_HEARTBEAT_TTL_SECONDS", 10.0)) * 1000)
    minimum_updated_at = now_ms() - stale_after_ms
    snapshot = blackboard.snapshot()
    navigators = [
        heartbeat
        for heartbeat in snapshot.get("heartbeats", [])
        if heartbeat.get("componentType") == "NAVIGATOR"
        and heartbeat.get("status") != "OFFLINE"
        and int(heartbeat.get("updatedAt") or 0) >= minimum_updated_at
    ]
    navigators.sort(key=lambda item: str(item.get("componentId", "")))
    return navigators


def runtime_state() -> dict[str, Any]:
    navigator_heartbeats = active_navigator_heartbeats()
    return {
        "map": {
            "width": blackboard.width,
            "height": blackboard.height,
            "chunkSize": blackboard.chunk_size,
        },
        "policy": simulation.config.policy,
        "assignmentPolicy": getattr(simulation.assignment_policy, "name", simulation.config.policy),
        "policies": POLICY_OPTIONS,
        "navigatorAlgorithm": simulation.config.navigator_algorithm,
        "navigatorAlgorithms": NAVIGATOR_OPTIONS,
        "navigatorCount": len(navigator_heartbeats),
        "navigatorIds": [item["componentId"] for item in navigator_heartbeats],
        "navigatorHeartbeats": navigator_heartbeats,
        "vehicleDeployment": simulation.vehicle_deployment,
        "tick": simulation.tick,
        "movementSteps": simulation.movement_steps,
        "scanRadius": simulation.config.scan_radius,
        "useStAstar": simulation.config.use_st_astar,
        "stAstarHorizon": simulation.config.st_astar_horizon,
        "embeddedSimulation": embedded_simulation_enabled,
        "broadcastInterval": broadcast_interval,
    }


def snapshot_with_runtime(
    map_version: int | None = None,
    map_generation: int | None = None,
) -> dict[str, Any]:
    snapshot = blackboard.snapshot_since(map_version, map_generation)
    snapshot["runtime"] = runtime_state()
    return snapshot


def snapshot_map_cursor(snapshot: dict[str, Any]) -> tuple[int, int] | None:
    if snapshot.get("mapDelta"):
        return int(snapshot["mapDelta"]["toVersion"]), int(snapshot["mapDelta"].get("generation", 0))
    if snapshot.get("map"):
        return int(snapshot["map"].get("version", 0)), int(snapshot["map"].get("generation", 0))
    return None

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount(
    "/Pathfinding-Visualizer-ThreeJS",
    StaticFiles(directory=PATHFINDING_DIST_DIR, html=True),
    name="pathfinding_frontend",
)


@app.on_event("startup")
async def on_startup() -> None:
    blackboard.ping()
    if embedded_simulation_enabled:
        simulation.start_background()
    else:
        blackboard.add_event("api", "EMBEDDED_SIMULATION_DISABLED", "API will not run the local simulation loop")
    asyncio.create_task(broadcast_loop())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await simulation.stop_background()


@app.get("/")
async def index() -> RedirectResponse:
    return RedirectResponse("/pathfinding")


@app.get("/pathfinding")
async def pathfinding_index() -> HTMLResponse:
    html = (PATHFINDING_DIST_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        "<head>",
        '<head><script>if ("serviceWorker" in navigator) { navigator.serviceWorker.getRegistrations().then(function(registrations) { registrations.forEach(function(registration) { registration.unregister(); }); }); }</script>',
    )
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/dashboard")
async def dashboard() -> RedirectResponse:
    return RedirectResponse("/pathfinding")


@app.get("/state")
async def get_state(
    map_version: int | None = Query(default=None, alias="mapVersion"),
    map_generation: int | None = Query(default=None, alias="mapGeneration"),
) -> dict[str, Any]:
    return await asyncio.to_thread(snapshot_with_runtime, map_version, map_generation)


@app.get("/runtime")
async def get_runtime() -> dict[str, Any]:
    return runtime_state()


@app.get("/health/redis")
async def redis_health() -> dict[str, Any]:
    return {
        "ok": blackboard.ping(),
        "url": redis_config.url,
        "prefix": redis_config.prefix,
        "deploymentRole": os.getenv("DEPLOYMENT_ROLE", "standalone"),
        "embeddedSimulation": embedded_simulation_enabled,
        "nodeId": os.getenv("NODE_ID", "computer-a"),
    }


@app.post("/auth/login")
async def login(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    payload = payload or {}
    result = auth_store.login(
        str(payload.get("username", "")),
        str(payload.get("password", "")),
    )
    if not result:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    return result


@app.get("/auth/me")
async def current_user(request: Request) -> dict[str, Any]:
    return request.state.user


@app.post("/auth/logout")
async def logout(request: Request) -> dict[str, bool]:
    auth_store.logout(bearer_token(request))
    return {"ok": True}


@app.get("/admin/users")
async def list_users() -> list[dict[str, Any]]:
    return auth_store.list_users()


@app.post("/admin/users")
async def create_user(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    payload = payload or {}
    try:
        return auth_store.create_user(
            str(payload.get("username", "")),
            str(payload.get("password", "")),
            str(payload.get("role", "")),
            str(payload.get("displayName", "")),
            bool(payload.get("enabled", True)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/admin/users/{username}")
async def update_user(
    username: str,
    payload: dict[str, Any] | None = Body(default=None),
) -> dict[str, Any]:
    payload = payload or {}
    try:
        return auth_store.update_user(
            username,
            password=str(payload["password"]) if payload.get("password") else None,
            role=str(payload["role"]) if payload.get("role") else None,
            display_name=str(payload["displayName"]) if "displayName" in payload else None,
            enabled=bool(payload["enabled"]) if "enabled" in payload else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/admin/users/{username}")
async def delete_user(username: str) -> dict[str, bool]:
    try:
        auth_store.delete_user(username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/replays")
async def list_replays() -> list[dict[str, Any]]:
    return replay_store.list_replays()


@app.get("/replays/{replay_id}")
async def get_replay(
    replay_id: str,
    max_frames: int = Query(default=120, alias="maxFrames", ge=2, le=300),
) -> dict[str, Any]:
    replay = await asyncio.to_thread(replay_store.get_replay, replay_id, max_frames)
    if not replay:
        raise HTTPException(status_code=404, detail="回放不存在")
    return replay


@app.delete("/replays/{replay_id}")
async def delete_replay(replay_id: str) -> dict[str, bool]:
    replay_store.delete_replay(replay_id)
    return {"ok": True}


@app.post("/runtime/policy")
async def set_runtime_policy(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    if blackboard.system_status == "RUNNING":
        raise HTTPException(status_code=409, detail="pause or stop the simulation before changing policy")
    payload = payload or {}
    return configure_policy(str(payload.get("policy", "nearest")))


@app.post("/runtime/navigator")
async def set_runtime_navigator(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    if blackboard.system_status == "RUNNING":
        raise HTTPException(status_code=409, detail="pause or stop the simulation before changing navigator")
    payload = payload or {}
    return configure_navigator_algorithm(str(payload.get("navigatorAlgorithm", "baseline")))


@app.post("/runtime/vehicles")
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


@app.post("/runtime/map")
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


@app.post("/runtime/obstacles")
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


@app.post("/runtime/obstacles/cell")
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


@app.post("/runtime/obstacles/cells")
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


@app.post("/robot/register")
async def register_robot(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.register_vehicle(payload["vehicleId"], payload["pose"])


@app.post("/robot/state")
async def update_robot_state(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.update_vehicle_state(payload)


@app.post("/robot/map-patch")
async def upload_map_patch(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.upload_map_patch(payload)


@app.post("/frontiers")
async def upload_frontier(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.save_frontier(payload)


@app.post("/navigation-requests")
async def create_navigation_request(payload: dict[str, Any]) -> dict[str, Any]:
    task = blackboard.get_task(payload["taskId"])
    if task:
        return blackboard.create_navigation_request(task, payload.get("priority", 5))
    return blackboard.save_navigation_request(payload)


@app.post("/navigation-requests/claim")
async def claim_navigation_request(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.claim_navigation_request(payload["navigatorId"])


@app.post("/navigation-plans")
async def write_navigation_plan(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.write_navigation_plan(payload)


@app.get("/vehicle-task")
async def get_vehicle_task(vehicleId: str) -> dict[str, Any] | None:
    return blackboard.get_vehicle_task(vehicleId)


@app.post("/heartbeat")
async def heartbeat(payload: dict[str, Any]) -> dict[str, Any]:
    return blackboard.update_heartbeat(
        payload["componentId"],
        payload["componentType"],
        payload.get("status", "READY"),
        payload.get("currentWorkId"),
        payload.get("host"),
        payload.get("pid"),
    )


@app.post("/control/start")
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
    result = blackboard.set_system_status("RUNNING")
    snapshot = snapshot_with_runtime()
    replay_store.start(request.state.user["username"], runtime_state(), snapshot)
    return result


@app.post("/control/pause")
async def control_pause() -> dict[str, Any]:
    return blackboard.set_system_status("PAUSED")


@app.post("/control/resume")
async def control_resume() -> dict[str, Any]:
    return blackboard.set_system_status("RUNNING")


@app.post("/control/stop")
async def control_stop() -> dict[str, Any]:
    result = blackboard.set_system_status("STOPPED")
    replay_store.record(snapshot_with_runtime(), force=True)
    replay_store.finish("COMPLETED")
    return result


@app.post("/control/reset")
async def control_reset() -> dict[str, Any]:
    replay_store.record(snapshot_with_runtime(), force=True)
    replay_store.finish("RESET")
    result = blackboard.set_system_status("RESET")
    simulation.tick = 0
    simulation.movement_steps = 0
    simulation.ensure_demo_vehicles()
    return result


@app.websocket("/ws")
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
