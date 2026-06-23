from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from ..middleware import bearer_token
from ..state import auth_store


router = APIRouter()


@router.post("/auth/login")
async def login(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    payload = payload or {}
    result = auth_store.login(
        str(payload.get("username", "")),
        str(payload.get("password", "")),
    )
    if not result:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    return result


@router.get("/auth/me")
async def current_user(request: Request) -> dict[str, Any]:
    return request.state.user


@router.post("/auth/logout")
async def logout(request: Request) -> dict[str, bool]:
    auth_store.logout(bearer_token(request))
    return {"ok": True}
