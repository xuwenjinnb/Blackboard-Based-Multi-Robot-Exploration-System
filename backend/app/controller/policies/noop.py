from __future__ import annotations

from typing import Any

from .base import AssignmentDecision


class NoopAssignmentPolicy:
    name = "noop"

    def select_assignments(
        self,
        snapshot: dict[str, Any],
        vehicles: list[dict[str, Any]],
        frontiers: list[dict[str, Any]],
        *,
        scan_radius: int,
    ) -> list[AssignmentDecision]:
        """输入格式与其它控制器算法一致，但 low_mdp 模式下不产生分配输出。

        low_mdp 由小车自己做局部决策，不需要 Controller 分配 frontier，
        因此这里始终返回空 AssignmentDecision 列表。
        """
        del snapshot, vehicles, frontiers, scan_radius
        return []
