from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .middleware import (
    PRIVATE_NETWORK_ORIGIN_REGEX,
    cors_origins_from_env,
    install_authorization_middleware,
)
from .routers import admin, auth, control, frontend, replay, robot, runtime
from .state import blackboard, embedded_simulation_enabled, simulation
from .websocket import broadcast_loop, register_websocket


app = FastAPI(title="Multi-car Blackboard Simulation")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_from_env(),
    allow_origin_regex=PRIVATE_NETWORK_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_authorization_middleware(app)

frontend.mount_static_files(app)
app.include_router(frontend.router)
app.include_router(runtime.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(replay.router)
app.include_router(control.router)
app.include_router(robot.router)
register_websocket(app)


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
