from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from ..state import auth_store


router = APIRouter()


@router.get("/admin/users")
async def list_users() -> list[dict[str, Any]]:
    return auth_store.list_users()


@router.post("/admin/users")
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


@router.put("/admin/users/{username}")
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


@router.delete("/admin/users/{username}")
async def delete_user(username: str) -> dict[str, bool]:
    try:
        auth_store.delete_user(username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}
