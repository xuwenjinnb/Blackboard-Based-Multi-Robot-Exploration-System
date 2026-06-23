from __future__ import annotations

from typing import Any

from .planners.cbs_planner import CBSPlanner
from .planners.factory import create_planner
from .planners.st_astar_planner import StAStarPlanner
from ..redis import Blackboard, now_ms
from ..config import SimulationConfig


class NavigatorComponent:
    """Navigator component: claim navigation requests and write path plans."""

    def __init__(self, blackboard: Blackboard, config: SimulationConfig, navigator_ids: list[str] | None = None) -> None:
        self.blackboard = blackboard
        self.config = config
        self.navigator_ids = navigator_ids or ["navigator-01"]

    def run_once(self) -> None:
        if self.config.navigator_algorithm.strip().lower() == "cbs":
            self.run_cbs_once()
            return

        for navigator_id in self.navigator_ids:
            claim = self.blackboard.claim_navigation_request(navigator_id)
            if not claim.get("claimed"):
                continue
            request = claim["request"]
            plan = self.plan_request(navigator_id, request)
            self.blackboard.write_navigation_plan(plan)

    def run_cbs_once(self) -> None:
        navigator_id = self.navigator_ids[0] if self.navigator_ids else "navigator-cbs"
        claim = self.blackboard.claim_navigation_requests(navigator_id)
        if not claim.get("claimed"):
            return

        snapshot = self.blackboard.snapshot_view()
        requests = claim["requests"]
        results = CBSPlanner(self.config).plan_batch(snapshot, requests)
        for request in requests:
            path, reason = results.get(request["requestId"], ([], "CBS did not return a result"))
            self.blackboard.write_navigation_plan(
                self.plan_from_result(
                    navigator_id,
                    request,
                    snapshot,
                    path,
                    reason,
                    planner_name="cbs",
                )
            )

    def plan_request(self, navigator_id: str, request: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.blackboard.snapshot_view()
        planner = create_planner(self.config, request)
        path, reason = planner.plan(snapshot, request)
        return self.plan_from_result(
            navigator_id,
            request,
            snapshot,
            path,
            reason,
            planner_name=planner.name,
        )

    def plan_from_result(
        self,
        navigator_id: str,
        request: dict[str, Any],
        snapshot: dict[str, Any],
        path: list[dict[str, Any]],
        reason: str | None,
        *,
        planner_name: str,
    ) -> dict[str, Any]:
        if path:
            return {
                "requestId": request["requestId"],
                "taskId": request["taskId"],
                "vehicleId": request["vehicleId"],
                "start": request["start"],
                "goal": request["goal"],
                "path": path,
                "cost": len(path),
                "distance": max(0, len(path) - 1),
                "estimatedTime": max(0, len(path) - 1),
                "mapVersion": snapshot["map"]["version"],
                "status": "SUCCESS",
                "planner": planner_name,
                "createdBy": navigator_id,
                "createdAt": now_ms(),
            }

        return {
            "requestId": request["requestId"],
            "taskId": request["taskId"],
            "vehicleId": request["vehicleId"],
            "start": request["start"],
            "goal": request["goal"],
            "path": [],
            "cost": 0,
            "distance": 0,
            "estimatedTime": 0,
            "mapVersion": snapshot["map"]["version"],
            "status": "NO_PATH",
            "failReason": reason or "no path",
            "planner": planner_name,
            "createdBy": navigator_id,
            "createdAt": now_ms(),
        }

    def build_time_reservations(
        self,
        snapshot: dict[str, Any],
        *,
        exclude_task_id: str | None = None,
        horizon: int = 96,
    ) -> tuple[dict[int, set[tuple[int, int]]], set[tuple[tuple[int, int], tuple[int, int], int]]]:
        return StAStarPlanner(self.config).build_time_reservations(
            snapshot,
            exclude_task_id=exclude_task_id,
            horizon=horizon,
        )
