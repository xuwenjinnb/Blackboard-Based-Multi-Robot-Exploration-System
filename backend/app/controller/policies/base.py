from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from typing import Protocol
except ImportError:  # Python < 3.8 compatibility for older conda envs.
    class Protocol:
        pass


@dataclass(frozen=True)
class AssignmentDecision:
    """控制器算法的输出：一条“车辆 -> frontier”的分配决策。"""

    vehicle_id: str
    frontier_id: str
    priority: int = 5
    score: float = 0.0


class AssignmentPolicy(Protocol):
    name: str

    def select_assignments(
        self,
        snapshot: dict[str, Any],
        vehicles: list[dict[str, Any]],
        frontiers: list[dict[str, Any]],
        *,
        scan_radius: int,
    ) -> list[AssignmentDecision]:
        """统一的控制器算法接口。

        输入:
        - snapshot: 黑板快照，包含 map、vehicles、frontiers、tasks、navigationRequests 等全局状态。
        - vehicles: 当前可分配的空闲车辆列表，来自 blackboard.idle_vehicles()。
        - frontiers: 当前 OPEN 状态的 frontier 列表，来自 blackboard.open_frontiers()。
        - scan_radius: 小车扫描半径，用于估计 frontier 周围是否还有未知区域。

        输出:
        - AssignmentDecision 列表，每条记录表示“哪辆车去哪个 frontier”。
        - 这里不直接输出路径，也不移动小车；Controller 会再创建 task 和 navigation request。
        """
        ...
