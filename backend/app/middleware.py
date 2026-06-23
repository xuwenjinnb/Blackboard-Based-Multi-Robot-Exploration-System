from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .redis import ROLE_ADMIN, ROLE_ANALYST, ROLE_OPERATOR
from .state import auth_store


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

PUBLIC_PATHS = {"/", "/pathfinding", "/dashboard", "/auth/login", "/health/redis"}
INTERNAL_PREFIXES = (
    "/robot/",
    "/frontiers",
    "/navigation-requests",
    "/navigation-plans",
    "/vehicle-task",
    "/heartbeat",
)


def cors_origins_from_env() -> list[str]:
    value = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if not value:
        return DEFAULT_CORS_ORIGINS
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def bearer_token(request: Request) -> str | None:
    value = request.headers.get("Authorization", "")
    return value[7:].strip() if value.startswith("Bearer ") else None


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


def install_authorization_middleware(app: FastAPI) -> None:
    app.middleware("http")(authorize_request)
