from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..state import replay_store


router = APIRouter()


@router.get("/replays")
async def list_replays() -> list[dict[str, Any]]:
    return replay_store.list_replays()


@router.get("/replays/{replay_id}")
async def get_replay(
    replay_id: str,
    max_frames: int = Query(default=120, alias="maxFrames", ge=2, le=300),
) -> dict[str, Any]:
    replay = await asyncio.to_thread(replay_store.get_replay, replay_id, max_frames)
    if not replay:
        raise HTTPException(status_code=404, detail="回放不存在")
    return replay


@router.delete("/replays/{replay_id}")
async def delete_replay(replay_id: str) -> dict[str, bool]:
    replay_store.delete_replay(replay_id)
    return {"ok": True}
