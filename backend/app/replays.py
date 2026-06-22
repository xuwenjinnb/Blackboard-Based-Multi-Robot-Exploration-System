from __future__ import annotations

import base64
import json
import math
import time
import uuid
import zlib
from typing import Any

import redis


def now_ms() -> int:
    return int(time.time() * 1000)


class ReplayStore:
    MIN_FRAME_INTERVAL_MS = 1200

    def __init__(self, client: redis.Redis, prefix: str) -> None:
        self.redis = client
        self.prefix = prefix.rstrip(":")
        self.active_id: str | None = None
        self.last_frame_at = 0
        self._mark_stale_replays()

    def key(self, name: str) -> str:
        return f"{self.prefix}:replays:{name}"

    @staticmethod
    def _encode_frame(snapshot: dict[str, Any]) -> str:
        compressed = zlib.compress(
            json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            level=4,
        )
        return base64.b64encode(compressed).decode("ascii")

    @staticmethod
    def _decode_frame(payload: str) -> dict[str, Any]:
        compressed = base64.b64decode(payload.encode("ascii"))
        frame = json.loads(zlib.decompress(compressed).decode("utf-8"))
        frame["snapshot"] = ReplayStore._compact_snapshot(frame.get("snapshot", {}))
        return frame

    @staticmethod
    def _compact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
        if snapshot.get("_replayCompact"):
            return snapshot
        map_data = dict(snapshot.get("map") or {})
        map_data.pop("chunks", None)
        cells = map_data.pop("cells", [])
        width = int(map_data.get("width", 0))
        height = int(map_data.get("height", 0))
        state_codes = {
            "UNKNOWN": "U",
            "OBSTACLE": "O",
            "FREE": "F",
            "VISITED": "V",
        }
        if width > 0 and height > 0 and cells:
            states = ["U"] * (width * height)
            for cell in cells:
                x = int(cell.get("x", -1))
                y = int(cell.get("y", -1))
                if 0 <= x < width and 0 <= y < height:
                    states[y * width + x] = state_codes.get(cell.get("state"), "U")
            map_data["cellStates"] = "".join(states)

        frontiers = snapshot.get("frontiers", [])
        tasks = snapshot.get("tasks", [])
        navigation_requests = snapshot.get("navigationRequests", [])
        source_plans = snapshot.get("navigationPlans", [])

        compact_frontiers = [
            ReplayStore._pick(
                item,
                "frontierId",
                "position",
                "status",
                "unknownGain",
                "discoveredBy",
                "assignedVehicleId",
            )
            for item in frontiers[-20:]
        ]
        compact_tasks = [
            ReplayStore._pick(
                item,
                "taskId",
                "frontierId",
                "vehicleId",
                "status",
                "target",
                "createdAt",
                "updatedAt",
            )
            for item in tasks[-20:]
        ]
        compact_requests = [
            ReplayStore._pick(
                item,
                "requestId",
                "taskId",
                "vehicleId",
                "status",
                "start",
                "goal",
                "claimedBy",
            )
            for item in navigation_requests[-12:]
        ]
        navigation_plans = []
        for plan in source_plans[-12:]:
            compact_plan = dict(plan)
            path = compact_plan.pop("path", [])
            compact_plan["pathLength"] = len(path)
            navigation_plans.append(
                ReplayStore._pick(
                    compact_plan,
                    "requestId",
                    "taskId",
                    "vehicleId",
                    "status",
                    "pathLength",
                    "createdBy",
                    "createdAt",
                )
            )

        compact = {
            "_replayCompact": True,
            "map": map_data,
            "vehicles": snapshot.get("vehicles", []),
            "frontiers": compact_frontiers,
            "tasks": compact_tasks,
            "navigationRequests": compact_requests,
            "navigationPlans": navigation_plans,
            "heartbeats": snapshot.get("heartbeats", []),
            "events": snapshot.get("events", [])[-20:],
            "dataCounts": {
                "frontiers": len(frontiers),
                "tasks": len(tasks),
                "navigationRequests": len(navigation_requests),
                "navigationPlans": len(source_plans),
                "events": len(snapshot.get("events", [])),
            },
            "systemStatus": snapshot.get("systemStatus"),
            "snapshotAt": snapshot.get("snapshotAt"),
            "runtime": snapshot.get("runtime", {}),
        }
        return compact

    @staticmethod
    def _pick(item: dict[str, Any], *keys: str) -> dict[str, Any]:
        return {key: item[key] for key in keys if key in item}

    def _mark_stale_replays(self) -> None:
        updates: dict[str, str] = {}
        timestamp = now_ms()
        for replay_id, raw in self.redis.hgetall(self.key("index")).items():
            meta = json.loads(raw)
            if meta.get("status") != "RUNNING":
                continue
            meta["status"] = "INTERRUPTED"
            meta["endedAt"] = timestamp
            meta["durationMs"] = max(0, timestamp - int(meta.get("startedAt", timestamp)))
            updates[replay_id] = json.dumps(meta, ensure_ascii=False)
        if updates:
            self.redis.hset(self.key("index"), mapping=updates)

    def start(self, operator: str, runtime: dict[str, Any], snapshot: dict[str, Any]) -> str:
        if self.active_id:
            self.finish("RESTARTED")
        replay_id = f"replay-{now_ms()}-{uuid.uuid4().hex[:6]}"
        meta = {
            "replayId": replay_id,
            "operator": operator,
            "status": "RUNNING",
            "startedAt": now_ms(),
            "endedAt": None,
            "frameCount": 0,
            "policy": runtime.get("policy"),
            "navigatorAlgorithm": runtime.get("navigatorAlgorithm"),
            "vehicleCount": len(snapshot.get("vehicles", [])),
            "mapWidth": snapshot.get("map", {}).get("width", 0),
            "mapHeight": snapshot.get("map", {}).get("height", 0),
        }
        self.redis.hset(self.key("index"), replay_id, json.dumps(meta, ensure_ascii=False))
        self.active_id = replay_id
        self.last_frame_at = 0
        self.record(snapshot, force=True)
        return replay_id

    def record(self, snapshot: dict[str, Any], *, force: bool = False) -> None:
        if not self.active_id:
            return
        timestamp = now_ms()
        if not force and timestamp - self.last_frame_at < self.MIN_FRAME_INTERVAL_MS:
            return
        frame = {
            "timestamp": timestamp,
            "snapshot": self._compact_snapshot(snapshot),
        }
        replay_id = self.active_id
        self.redis.rpush(self.key(f"frames:{replay_id}"), self._encode_frame(frame))
        raw = self.redis.hget(self.key("index"), replay_id)
        if raw:
            meta = json.loads(raw)
            meta["frameCount"] = int(meta.get("frameCount", 0)) + 1
            meta["lastCoverage"] = coverage(snapshot)
            meta["movementSteps"] = snapshot.get("runtime", {}).get("movementSteps", 0)
            self.redis.hset(self.key("index"), replay_id, json.dumps(meta, ensure_ascii=False))
        self.last_frame_at = timestamp

    def should_record(self) -> bool:
        return bool(
            self.active_id
            and now_ms() - self.last_frame_at >= self.MIN_FRAME_INTERVAL_MS
        )

    def finish(self, status: str = "COMPLETED") -> None:
        if not self.active_id:
            return
        raw = self.redis.hget(self.key("index"), self.active_id)
        if raw:
            meta = json.loads(raw)
            meta["status"] = status
            meta["endedAt"] = now_ms()
            meta["durationMs"] = meta["endedAt"] - int(meta["startedAt"])
            self.redis.hset(self.key("index"), self.active_id, json.dumps(meta, ensure_ascii=False))
        self.active_id = None
        self.last_frame_at = 0

    def list_replays(self) -> list[dict[str, Any]]:
        items = [json.loads(raw) for raw in self.redis.hvals(self.key("index"))]
        return sorted(items, key=lambda item: int(item["startedAt"]), reverse=True)

    def get_replay(self, replay_id: str, max_frames: int = 120) -> dict[str, Any] | None:
        raw = self.redis.hget(self.key("index"), replay_id)
        if not raw:
            return None
        frame_key = self.key(f"frames:{replay_id}")
        total = self.redis.llen(frame_key)
        if total <= max_frames:
            payloads = self.redis.lrange(frame_key, 0, -1)
        else:
            step = (total - 1) / (max_frames - 1)
            indexes = sorted({min(total - 1, math.floor(index * step)) for index in range(max_frames)})
            pipeline = self.redis.pipeline(transaction=False)
            for index in indexes:
                pipeline.lindex(frame_key, index)
            payloads = [payload for payload in pipeline.execute() if payload]
        frames = [self._decode_frame(payload) for payload in payloads]
        meta = json.loads(raw)
        meta["returnedFrameCount"] = len(frames)
        meta["sampled"] = total > len(frames)
        return {"meta": meta, "frames": frames}

    def delete_replay(self, replay_id: str) -> None:
        self.redis.hdel(self.key("index"), replay_id)
        self.redis.delete(self.key(f"frames:{replay_id}"))
        if self.active_id == replay_id:
            self.active_id = None
            self.last_frame_at = 0


def coverage(snapshot: dict[str, Any]) -> float:
    cells = snapshot.get("map", {}).get("cells", [])
    if not cells:
        return 0.0
    known = sum(1 for cell in cells if cell.get("state") != "UNKNOWN")
    return round(known / len(cells) * 100, 2)
