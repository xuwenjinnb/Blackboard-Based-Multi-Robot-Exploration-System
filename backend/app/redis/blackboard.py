from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from typing import Any, Callable, TypeVar

import redis

from .base import Blackboard, now_ms
from .client import create_redis_client
from .config import RedisConfig


T = TypeVar("T")


class RedisBlackboard(Blackboard):
    """Redis-backed implementation of the Blackboard method contract."""

    COLLECTIONS = {
        "vehicles": "vehicles",
        "frontiers": "frontiers",
        "tasks": "tasks",
        "navigation_requests": "navigation_requests",
        "navigation_plans": "navigation_plans",
        "heartbeats": "heartbeats",
    }

    def __init__(
        self,
        redis_config: RedisConfig | str,
        *,
        prefix: str = "inspection",
        width: int = 50,
        height: int = 50,
        chunk_size: int = 10,
        reset_on_start: bool = False,
    ) -> None:
        self.width = self._normalize_dimension(width, "width")
        self.height = self._normalize_dimension(height, "height")
        self.chunk_size = self._normalize_chunk_size(chunk_size)
        self.prefix = prefix.rstrip(":")
        self.redis = create_redis_client(redis_config)
        self.lock = threading.RLock()
        self._local = threading.local()
        self._sync_depth = 0
        self._system_status = "STOPPED"
        self._persisted_event_ids: set[str] = set()
        self._replace_events = False
        self._persisted_hashes: dict[str, dict[str, str]] = {}
        self._persisted_map_deltas: list[str] = []
        self._persisted_map_signature: tuple[int, int, int, int, int] | None = None
        self._persisted_obstacles: set[tuple[int, int]] = set()
        self._map_delta_log: list[dict[str, Any]] = []
        self._map_generation = now_ms()
        self.true_obstacles = self._build_truth_obstacles()

        if reset_on_start or not self.redis.exists(self.key("initialized")):
            self.reset()
        else:
            with self.lock:
                self._load_state()

    def key(self, name: str) -> str:
        return f"{self.prefix}:{name}"

    @staticmethod
    def _encode(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode(value: str | None, default: Any = None) -> Any:
        return json.loads(value) if value is not None else default

    @staticmethod
    def _sanitize_frontier(frontier: dict[str, Any]) -> dict[str, Any]:
        frontier.pop("score", None)
        return frontier

    @staticmethod
    def _frontier_in_bounds(frontier: dict[str, Any], width: int, height: int) -> bool:
        position = frontier.get("position") or {}
        try:
            x = int(position["x"])
            y = int(position["y"])
        except (KeyError, TypeError, ValueError):
            return False
        return 0 <= x < width and 0 <= y < height

    def _sanitize_frontier_for_map(
        self,
        frontier: dict[str, Any],
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        sanitized = self._sanitize_frontier(frontier)
        map_width = self.width if width is None else int(width)
        map_height = self.height if height is None else int(height)
        if (
            sanitized.get("status") in {"OPEN", "ASSIGNED"}
            and not self._frontier_in_bounds(sanitized, map_width, map_height)
        ):
            sanitized["status"] = "CLOSED"
            sanitized["unknownGain"] = 0
        return sanitized

    @property
    def _sync_depth(self) -> int:
        return getattr(self._local, "sync_depth", 0)

    @_sync_depth.setter
    def _sync_depth(self, value: int) -> None:
        self._local.sync_depth = value

    @property
    def system_status(self) -> str:
        if self._sync_depth:
            return self._system_status
        return self.redis.hget(self.key("system"), "status") or "STOPPED"

    @system_status.setter
    def system_status(self, value: str) -> None:
        self._system_status = value
        if not self._sync_depth:
            self.redis.hset(self.key("system"), "status", value)

    def ping(self) -> bool:
        return bool(self.redis.ping())

    @contextmanager
    def _redis_guard(self):
        with self.lock:
            with self.redis.lock(
                self.key("lock"),
                timeout=30,
                blocking_timeout=10,
                thread_local=False,
            ):
                yield

    def _execute(
        self,
        method: Callable[..., T],
        *args: Any,
        write: bool,
        **kwargs: Any,
    ) -> T:
        if self._sync_depth:
            return method(self, *args, **kwargs)

        with self._redis_guard():
            self._load_state()
            self._sync_depth += 1
            try:
                result = method(self, *args, **kwargs)
                if write:
                    self._persist_state()
                return result
            finally:
                self._sync_depth -= 1

    @contextmanager
    def batch(self):
        if self._sync_depth:
            yield self
            return

        with self._redis_guard():
            self._load_state()
            self._sync_depth += 1
            succeeded = False
            try:
                yield self
                succeeded = True
            finally:
                self._sync_depth -= 1
                if succeeded:
                    self._persist_state()

    def _load_hash(self, name: str) -> dict[str, dict[str, Any]]:
        raw = self.redis.hgetall(self.key(name))
        stored = {field: value for field, value in raw.items() if field != "__empty__"}
        self._persisted_hashes[name] = stored
        return {field: self._decode(value, {}) for field, value in stored.items()}

    def _load_state(self) -> None:
        meta = self.redis.hgetall(self.key("map:meta"))
        if not meta:
            self._sync_depth += 1
            try:
                self._prime_persisted_state_for_reset()
                self._replace_events = True
                Blackboard.reset(self)
                self._persist_state()
            finally:
                self._sync_depth -= 1
            return

        width = int(meta.get("width", self.width))
        height = int(meta.get("height", self.height))
        chunk_size = int(meta.get("chunkSize", self.chunk_size))
        generation = int(meta.get("generation", meta.get("updatedAt", now_ms())))
        map_signature = (
            generation,
            int(meta.get("version", 1)),
            width,
            height,
            chunk_size,
        )
        map_changed = (
            not hasattr(self, "map")
            or self._persisted_map_signature != map_signature
        )

        collection_names = list(self.COLLECTIONS.values())
        with self.redis.pipeline(transaction=False) as pipe:
            if map_changed:
                pipe.hgetall(self.key("map:chunks"))
                pipe.hgetall(self.key("map:cells"))
                pipe.smembers(self.key("true_obstacles"))
                pipe.exists(self.key("true_obstacles:initialized"))
                pipe.lrange(self.key("map:deltas"), 0, -1)
            for name in collection_names:
                pipe.hgetall(self.key(name))
            pipe.xrevrange(self.key("events"), max="+", min="-", count=120)
            pipe.hget(self.key("system"), "status")
            pipe.hgetall(self.key("counters"))
            results = pipe.execute()

        cursor = 0
        if map_changed:
            raw_chunks = results[cursor]
            raw_cells = results[cursor + 1]
            raw_obstacles = results[cursor + 2]
            obstacles_initialized = bool(results[cursor + 3])
            encoded_deltas = results[cursor + 4]
            cursor += 5

            stored_chunks = {
                field: value
                for field, value in raw_chunks.items()
                if field != "__empty__"
            }
            self._persisted_hashes["map:chunks"] = stored_chunks
            chunks = [self._decode(value, {}) for value in stored_chunks.values()]
            chunks.sort(
                key=lambda chunk: (
                    int(chunk.get("origin", {}).get("y", 0)),
                    int(chunk.get("origin", {}).get("x", 0)),
                )
            )
            previous_dimensions = (self.width, self.height, self.chunk_size)
            self.width = width
            self.height = height
            self.chunk_size = chunk_size
            if chunks:
                try:
                    cells = self._cells_from_chunks(chunks)
                finally:
                    self.width, self.height, self.chunk_size = previous_dimensions
            else:
                stored_cells = {
                    field: value
                    for field, value in raw_cells.items()
                    if field != "__empty__"
                }
                self._persisted_hashes["map:cells"] = stored_cells
                try:
                    cells = [
                        self._decode(value, {})
                        for value in stored_cells.values()
                    ]
                    cells = [
                        cell
                        for cell in cells
                        if 0 <= int(cell.get("x", -1)) < self.width
                        and 0 <= int(cell.get("y", -1)) < self.height
                    ]
                    cells.sort(key=lambda cell: (int(cell["y"]), int(cell["x"])))
                    if not cells:
                        cells = self._build_empty_cells(int(meta.get("updatedAt", now_ms())))
                finally:
                    self.width, self.height, self.chunk_size = previous_dimensions
                chunks = []

            self.width = width
            self.height = height
            self.chunk_size = chunk_size
            self._map_generation = generation
            self.map = {
                "mapId": meta.get("mapId", "demo-map"),
                "width": width,
                "height": height,
                "chunkSize": chunk_size,
                "version": map_signature[1],
                "generation": generation,
                "cells": cells,
                "chunks": self._build_chunks_from_cells(cells),
                "updatedAt": int(meta.get("updatedAt", 0)),
            }
            if raw_obstacles or obstacles_initialized:
                self.true_obstacles = {
                    tuple(map(int, value.split(":")))
                    for value in raw_obstacles
                }
            else:
                self.true_obstacles = self._build_truth_obstacles()
            self._persisted_obstacles = set(self.true_obstacles)
            self._persisted_map_deltas = list(encoded_deltas)
            self._map_delta_log = [
                self._decode(value, {})
                for value in encoded_deltas
            ]
            self._persisted_map_signature = map_signature

        collection_results = results[cursor:cursor + len(collection_names)]
        cursor += len(collection_names)
        for (attribute, redis_name), raw in zip(self.COLLECTIONS.items(), collection_results):
            stored = {
                field: value
                for field, value in raw.items()
                if field != "__empty__"
            }
            self._persisted_hashes[redis_name] = stored
            decoded = {
                field: self._decode(value, {})
                for field, value in stored.items()
            }
            if attribute == "frontiers":
                decoded = {
                    field: self._sanitize_frontier_for_map(frontier)
                    for field, frontier in decoded.items()
                }
            setattr(
                self,
                attribute,
                decoded,
            )

        raw_events = results[cursor]
        status = results[cursor + 1]
        raw_counters = results[cursor + 2]
        self.events = list(reversed([
            self._decode(fields.get("data"), {})
            for _, fields in raw_events
        ]))
        self._persisted_event_ids = {
            event["eventId"]
            for event in self.events
            if event.get("eventId")
        }
        self._replace_events = False
        self._system_status = status or "STOPPED"
        self._counters = {
            name: int(value)
            for name, value in raw_counters.items()
        }
        for name in ("event", "task", "frontier", "request", "plan", "patch"):
            self._counters.setdefault(name, 0)

    def _load_map_deltas(self) -> None:
        encoded = self.redis.lrange(self.key("map:deltas"), 0, -1)
        self._persisted_map_deltas = list(encoded)
        self._map_delta_log = [
            self._decode(value, {})
            for value in encoded
        ]

    def _map_signature(self) -> tuple[int, int, int, int, int]:
        return (
            int(self.map.get("generation", 0)),
            int(self.map.get("version", 0)),
            int(self.map.get("width", self.width)),
            int(self.map.get("height", self.height)),
            int(self.map.get("chunkSize", self.chunk_size)),
        )

    def _load_map_chunks(self) -> list[dict[str, Any]]:
        raw_chunks = self.redis.hgetall(self.key("map:chunks"))
        stored_chunks = {
            field: value
            for field, value in raw_chunks.items()
            if field != "__empty__"
        }
        self._persisted_hashes["map:chunks"] = stored_chunks
        chunks = [self._decode(value, {}) for value in stored_chunks.values()]
        chunks.sort(
            key=lambda chunk: (
                int(chunk.get("origin", {}).get("y", 0)),
                int(chunk.get("origin", {}).get("x", 0)),
            )
        )
        return chunks

    def _load_legacy_map_cells(self) -> list[dict[str, Any]]:
        raw_cells = self.redis.hgetall(self.key("map:cells"))
        stored_cells = {
            field: value
            for field, value in raw_cells.items()
            if field != "__empty__"
        }
        self._persisted_hashes["map:cells"] = stored_cells
        cells = [self._decode(value, {}) for value in stored_cells.values()]
        cells.sort(key=lambda cell: (int(cell["y"]), int(cell["x"])))
        return cells

    def _sync_hash(
        self,
        pipe: redis.client.Pipeline,
        name: str,
        values: dict[str, dict[str, Any]],
    ) -> None:
        key = self.key(name)
        current = {field: self._encode(value) for field, value in values.items()}
        previous = self._persisted_hashes.get(name, {})
        removed = set(previous) - set(current)
        changed = {
            field: value
            for field, value in current.items()
            if previous.get(field) != value
        }

        if removed:
            pipe.hdel(key, *removed)
        if changed:
            pipe.hset(key, mapping=changed)
        if current:
            pipe.hdel(key, "__empty__")
        else:
            pipe.hset(key, "__empty__", "1")
        self._persisted_hashes[name] = current

    def _persist_state(self) -> None:
        map_signature = self._map_signature()
        map_changed = map_signature != self._persisted_map_signature
        with self.redis.pipeline(transaction=True) as pipe:
            pipe.hset(
                self.key("map:meta"),
                mapping={
                    "mapId": self.map["mapId"],
                    "width": self.map["width"],
                    "height": self.map["height"],
                    "chunkSize": self.map.get("chunkSize", self.chunk_size),
                    "version": self.map["version"],
                    "generation": self.map.get("generation", getattr(self, "_map_generation", self.map["updatedAt"])),
                    "updatedAt": self.map["updatedAt"],
                },
            )
            if map_changed:
                self._rebuild_map_chunks_locked()
                chunks = {
                    chunk["chunkId"]: chunk
                    for chunk in self.map["chunks"]
                }
                self._sync_hash(pipe, "map:chunks", chunks)
            encoded_deltas = [
                self._encode(delta)
                for delta in self._map_delta_log[-120:]
            ]
            previous_deltas = self._persisted_map_deltas
            overlap = 0
            for size in range(min(len(previous_deltas), len(encoded_deltas)), 0, -1):
                if previous_deltas[-size:] == encoded_deltas[:size]:
                    overlap = size
                    break
            new_deltas = encoded_deltas[overlap:]
            if not encoded_deltas and previous_deltas:
                pipe.delete(self.key("map:deltas"))
            elif new_deltas:
                pipe.rpush(self.key("map:deltas"), *new_deltas)
                pipe.ltrim(self.key("map:deltas"), -120, -1)
            if self._persisted_hashes.get("map:cells") or self.redis.exists(self.key("map:cells")):
                pipe.delete(self.key("map:cells"))
                self._persisted_hashes["map:cells"] = {}

            for attribute, redis_name in self.COLLECTIONS.items():
                self._sync_hash(pipe, redis_name, getattr(self, attribute))

            if self._replace_events:
                pipe.delete(self.key("events"))
                events_to_append = self.events[-120:]
            else:
                events_to_append = [
                    event
                    for event in self.events[-120:]
                    if event.get("eventId") not in self._persisted_event_ids
                ]
            for event in events_to_append:
                pipe.xadd(
                    self.key("events"),
                    {"data": self._encode(event)},
                    maxlen=120,
                    approximate=True,
                )

            pipe.hset(self.key("system"), mapping={"status": self._system_status})
            pipe.hset(self.key("counters"), mapping=self._counters)
            obstacle_key = self.key("true_obstacles")
            if self.true_obstacles != self._persisted_obstacles:
                pipe.delete(obstacle_key)
                if self.true_obstacles:
                    pipe.sadd(
                        obstacle_key,
                        *(f"{x}:{y}" for x, y in self.true_obstacles),
                    )
                self._persisted_obstacles = set(self.true_obstacles)
            pipe.set(self.key("true_obstacles:initialized"), "1")
            pipe.set(self.key("initialized"), now_ms())
            pipe.execute()
        self._persisted_map_deltas = encoded_deltas
        self._persisted_map_signature = map_signature
        self._persisted_event_ids = {
            event["eventId"]
            for event in self.events[-120:]
            if event.get("eventId")
        }
        self._replace_events = False

    def delete_namespace(self) -> None:
        keys = list(self.redis.scan_iter(match=f"{self.prefix}:*"))
        if keys:
            self.redis.delete(*keys)

    def reset(self) -> None:
        if self._sync_depth:
            Blackboard.reset(self)
            return
        with self._redis_guard():
            self._sync_depth += 1
            try:
                self._prime_persisted_state_for_reset()
                self._replace_events = True
                self._persisted_event_ids = set()
                self._persisted_map_deltas = []
                self._persisted_map_signature = None
                self.redis.delete(self.key("map:deltas"))
                Blackboard.reset(self)
                self._persist_state()
            finally:
                self._sync_depth -= 1

    def _prime_persisted_state_for_reset(self) -> None:
        hash_names = [
            "map:chunks",
            "map:cells",
            *self.COLLECTIONS.values(),
        ]
        with self.redis.pipeline(transaction=False) as pipe:
            for name in hash_names:
                pipe.hgetall(self.key(name))
            pipe.smembers(self.key("true_obstacles"))
            raw_results = pipe.execute()

        for name, raw_hash in zip(hash_names, raw_results[: len(hash_names)]):
            self._persisted_hashes[name] = {
                field: value
                for field, value in raw_hash.items()
                if field != "__empty__"
            }
        raw_obstacles = raw_results[len(hash_names)]
        self._persisted_obstacles = {
            tuple(map(int, value.split(":")))
            for value in raw_obstacles
        }

    def next_id(self, prefix: str) -> str:
        return self._execute(Blackboard.next_id, prefix, write=True)

    def add_event(self, source: str, event_type: str, message: str) -> dict[str, Any]:
        return self._execute(Blackboard.add_event, source, event_type, message, write=True)

    def snapshot(self) -> dict[str, Any]:
        if self._sync_depth:
            return Blackboard.snapshot(self)

        collection_names = list(self.COLLECTIONS.values())
        with self.redis.pipeline(transaction=False) as pipe:
            pipe.hgetall(self.key("map:meta"))
            pipe.hgetall(self.key("map:chunks"))
            pipe.hgetall(self.key("map:cells"))
            for name in collection_names:
                pipe.hgetall(self.key(name))
            pipe.xrevrange(self.key("events"), max="+", min="-", count=120)
            pipe.hget(self.key("system"), "status")
            results = pipe.execute()

        meta = results[0]
        raw_chunks = results[1]
        raw_cells = results[2]
        collection_results = results[3 : 3 + len(collection_names)]
        raw_events = results[-2]
        status = results[-1] or "STOPPED"

        chunks = [
            self._decode(value, {})
            for field, value in raw_chunks.items()
            if field != "__empty__"
        ]
        chunks.sort(
            key=lambda chunk: (
                int(chunk.get("origin", {}).get("y", 0)),
                int(chunk.get("origin", {}).get("x", 0)),
            )
        )
        current_width = int(meta.get("width", self.width))
        current_height = int(meta.get("height", self.height))
        current_chunk_size = int(meta.get("chunkSize", self.chunk_size))
        updated_at = int(meta.get("updatedAt", 0))
        previous = (self.width, self.height, self.chunk_size)
        self.width = current_width
        self.height = current_height
        self.chunk_size = current_chunk_size
        try:
            cells = self._cells_from_chunks(chunks)
            if not cells:
                cells = [
                    self._decode(value, {})
                    for field, value in raw_cells.items()
                    if field != "__empty__"
                ]
                cells.sort(key=lambda cell: (int(cell["y"]), int(cell["x"])))
                if not cells:
                    cells = self._build_empty_cells(updated_at or now_ms())
            map_data = {
                "mapId": meta.get("mapId", "demo-map"),
                "width": current_width,
                "height": current_height,
                "chunkSize": current_chunk_size,
                "version": int(meta.get("version", 1)),
                "generation": int(meta.get("generation", updated_at)),
                "cells": cells,
                "chunks": self._build_chunks_from_cells(cells),
                "updatedAt": updated_at,
            }
        finally:
            self.width, self.height, self.chunk_size = previous

        collections: dict[str, list[dict[str, Any]]] = {}
        for name, raw in zip(collection_names, collection_results):
            items = [
                self._decode(value, {})
                for field, value in raw.items()
                if field != "__empty__"
            ]
            if name == "frontiers":
                items = [
                    self._sanitize_frontier_for_map(
                        frontier,
                        width=current_width,
                        height=current_height,
                    )
                    for frontier in items
                ]
            collections[name] = items

        return {
            "map": map_data,
            "vehicles": collections["vehicles"],
            "frontiers": collections["frontiers"],
            "tasks": collections["tasks"],
            "navigationRequests": collections["navigation_requests"],
            "navigationPlans": collections["navigation_plans"],
            "heartbeats": collections["heartbeats"],
            "events": list(reversed([
                self._decode(fields.get("data"), {})
                for _, fields in raw_events
            ])),
            "systemStatus": status,
            "snapshotAt": now_ms(),
        }

    def snapshot_since(
        self,
        map_version: int | None = None,
        map_generation: int | None = None,
    ) -> dict[str, Any]:
        if self._sync_depth:
            return Blackboard.snapshot_since(self, map_version, map_generation)

        if map_version is None:
            return self.snapshot()

        with self.redis.pipeline(transaction=False) as pipe:
            pipe.hgetall(self.key("map:meta"))
            pipe.lrange(self.key("map:deltas"), 0, -1)
            meta, encoded_deltas = pipe.execute()
        current_version = int(meta.get("version", 1))
        current_width = int(meta.get("width", self.width))
        current_height = int(meta.get("height", self.height))
        current_chunk_size = int(meta.get("chunkSize", self.chunk_size))
        current_generation = int(meta.get("generation", meta.get("updatedAt", 0)))
        with self.lock:
            previous = (getattr(self, "map", None), self.width, self.height, self.chunk_size)
            self.width = current_width
            self.height = current_height
            self.chunk_size = current_chunk_size
            self.map = {
                "mapId": meta.get("mapId", "demo-map"),
                "width": self.width,
                "height": self.height,
                "chunkSize": self.chunk_size,
                "version": current_version,
                "generation": current_generation,
                "cells": [],
                "chunks": [],
                "updatedAt": int(meta.get("updatedAt", 0)),
            }
            self._map_delta_log = [
                self._decode(value, {})
                for value in encoded_deltas
            ]
            try:
                delta = self._map_delta_since_locked(int(map_version), map_generation)
            finally:
                previous_map, previous_width, previous_height, previous_chunk_size = previous
                if previous_map is not None:
                    self.map = previous_map
                self.width = previous_width
                self.height = previous_height
                self.chunk_size = previous_chunk_size
        if delta is None:
            return self.snapshot()

        collection_names = list(self.COLLECTIONS.values())
        with self.redis.pipeline(transaction=False) as pipe:
            for name in collection_names:
                pipe.hgetall(self.key(name))
            pipe.xrevrange(self.key("events"), max="+", min="-", count=40)
            pipe.hget(self.key("system"), "status")
            results = pipe.execute()

        collection_results = results[:len(collection_names)]
        raw_events = results[-2]
        status = results[-1] or "STOPPED"
        collections: dict[str, list[dict[str, Any]]] = {}
        for name, raw in zip(collection_names, collection_results):
            items = [
                self._decode(value, {})
                for field, value in raw.items()
                if field != "__empty__"
            ]
            if name == "frontiers":
                items = [
                    self._sanitize_frontier_for_map(
                        frontier,
                        width=current_width,
                        height=current_height,
                    )
                    for frontier in items
                ]
            collections[name] = items

        snapshot = {
            "map": {
                "mapId": meta.get("mapId", "demo-map"),
                "width": current_width,
                "height": current_height,
                "chunkSize": current_chunk_size,
                "version": current_version,
                "generation": current_generation,
                "updatedAt": int(meta.get("updatedAt", 0)),
            },
            "vehicles": collections["vehicles"],
            "frontiers": collections["frontiers"],
            "tasks": collections["tasks"],
            "navigationRequests": collections["navigation_requests"],
            "navigationPlans": collections["navigation_plans"],
            "heartbeats": collections["heartbeats"],
            "events": list(reversed([
                self._decode(fields.get("data"), {})
                for _, fields in raw_events
            ])),
            "systemStatus": status,
            "snapshotAt": now_ms(),
        }
        snapshot["mapDelta"] = delta
        return snapshot

    def set_system_status(self, status: str) -> dict[str, Any]:
        return self._execute(Blackboard.set_system_status, status, write=True)

    def register_vehicle(self, vehicle_id: str, pose: dict[str, Any]) -> dict[str, Any]:
        return self._execute(Blackboard.register_vehicle, vehicle_id, pose, write=True)

    def update_vehicle_state(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._execute(Blackboard.update_vehicle_state, data, write=True)

    def update_heartbeat(
        self,
        component_id: str,
        component_type: str,
        status: str,
        current_work_id: str | None,
        host: str | None = None,
        pid: int | None = None,
    ) -> dict[str, Any]:
        return self._execute(
            Blackboard.update_heartbeat,
            component_id,
            component_type,
            status,
            current_work_id,
            host,
            pid,
            write=True,
        )

    def cell_at(self, x: int, y: int) -> dict[str, Any] | None:
        return self._execute(Blackboard.cell_at, x, y, write=False)

    def upload_map_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        return self._execute(Blackboard.upload_map_patch, patch, write=True)

    def reset_perception_map_locked(self) -> int:
        return self._execute(Blackboard.reset_perception_map_locked, write=True)

    def configure_map(self, *, width: int, height: int, chunk_size: int | None = None) -> dict[str, Any]:
        return self._execute(
            Blackboard.configure_map,
            width=width,
            height=height,
            chunk_size=chunk_size,
            write=True,
        )

    def configure_obstacles(
        self,
        *,
        mode: str,
        obstacles: list[dict[str, Any]] | None = None,
        density: float = 0.18,
        seed: int | None = None,
        protected_points: set[tuple[int, int]] | None = None,
        count: int | None = None,
    ) -> dict[str, Any]:
        return self._execute(
            Blackboard.configure_obstacles,
            mode=mode,
            obstacles=obstacles,
            density=density,
            seed=seed,
            protected_points=protected_points,
            count=count,
            write=True,
        )

    def set_obstacle_at(self, x: int, y: int, blocked: bool | None = None) -> dict[str, Any]:
        return self._execute(Blackboard.set_obstacle_at, x, y, blocked, write=True)

    def set_obstacles_at(self, cells: list[dict[str, Any]]) -> dict[str, Any]:
        return self._execute(Blackboard.set_obstacles_at, cells, write=True)

    def save_frontier(self, frontier: dict[str, Any]) -> dict[str, Any]:
        return self._execute(Blackboard.save_frontier, frontier, write=True)

    def refresh_frontiers_locked(self, scan_radius: int = 2) -> int:
        return self._execute(Blackboard.refresh_frontiers_locked, scan_radius, write=True)

    def create_task_for_frontier(self, vehicle_id: str, frontier: dict[str, Any]) -> dict[str, Any]:
        return self._execute(Blackboard.create_task_for_frontier, vehicle_id, frontier, write=True)

    def create_navigation_request(self, task: dict[str, Any], priority: int = 5) -> dict[str, Any]:
        return self._execute(Blackboard.create_navigation_request, task, priority, write=True)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._execute(Blackboard.get_task, task_id, write=False)

    def save_navigation_request(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._execute(Blackboard.save_navigation_request, request, write=True)

    def has_active_request_for_task(self, task_id: str) -> bool:
        return self._execute(Blackboard.has_active_request_for_task, task_id, write=False)

    def claim_navigation_request(self, navigator_id: str) -> dict[str, Any]:
        return self._execute(Blackboard.claim_navigation_request, navigator_id, write=True)

    def claim_navigation_requests(self, navigator_id: str, limit: int | None = None) -> dict[str, Any]:
        return self._execute(Blackboard.claim_navigation_requests, navigator_id, limit, write=True)

    def write_navigation_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        return self._execute(Blackboard.write_navigation_plan, plan, write=True)

    def get_vehicle_task(self, vehicle_id: str) -> dict[str, Any] | None:
        return self._execute(Blackboard.get_vehicle_task, vehicle_id, write=False)

    def mark_task_running(self, task_id: str) -> None:
        return self._execute(Blackboard.mark_task_running, task_id, write=True)

    def mark_task_progress(self, task_id: str, step_index: int) -> None:
        return self._execute(Blackboard.mark_task_progress, task_id, step_index, write=True)

    def mark_task_done(self, task_id: str) -> None:
        return self._execute(Blackboard.mark_task_done, task_id, write=True)

    def report_blocked(self, vehicle_id: str, task_id: str, blocked_at: dict[str, int]) -> None:
        return self._execute(Blackboard.report_blocked, vehicle_id, task_id, blocked_at, write=True)

    def active_task_vehicle_ids(self) -> set[str]:
        return self._execute(Blackboard.active_task_vehicle_ids, write=False)

    def open_frontiers(self) -> list[dict[str, Any]]:
        return self._execute(Blackboard.open_frontiers, write=False)

    def idle_vehicles(self) -> list[dict[str, Any]]:
        return self._execute(Blackboard.idle_vehicles, write=False)

    def pending_tasks_without_request(self) -> list[dict[str, Any]]:
        return self._execute(Blackboard.pending_tasks_without_request, write=False)

    def is_truth_blocked(self, point: dict[str, int]) -> bool:
        return self._execute(Blackboard.is_truth_blocked, point, write=False)
