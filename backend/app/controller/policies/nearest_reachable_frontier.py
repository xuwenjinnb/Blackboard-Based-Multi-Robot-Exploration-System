from __future__ import annotations

from typing import Any

from ...pathfinding import manhattan, shortest_path_distances
from .base import AssignmentDecision
from .helpers import occupied_positions, point_tuple, unknown_cells_visible_from


class NearestReachableFrontierPolicy:
    """最近可达 frontier 分配策略。

    该策略是 Controller 内部的任务分配算法接口实现。它不直接读写 Redis，
    而是接收 Controller 从 Redis 黑板中取出的快照数据，输出车辆到 frontier
    的分配决策；后续由 Controller 创建 task 和 navigation request。
    """

    name = "nearest-reachable-frontier"

    def select_assignments(
        self,
        snapshot: dict[str, Any],
        vehicles: list[dict[str, Any]],
        frontiers: list[dict[str, Any]],
        *,
        scan_radius: int,
    ) -> list[AssignmentDecision]:
        """输入黑板快照、空闲车辆和 OPEN frontier，输出车辆到 frontier 的分配结果。

        本策略会使用 snapshot 中的:
        - map: 计算从车辆当前位置到 frontier 的真实路径距离。
        - vehicles/tasks: 统计已经被车辆或未完成任务占用的位置，作为防重复分配的补充约束。

        输出的 AssignmentDecision 只表示目标分配；后续路径由 Navigator 根据 task/request 规划。
        """
        # available 表示本轮还没有被其他车辆选中的候选 frontier。
        # open_frontiers() 已经排除了 ASSIGNED frontier，这里再防止同一轮重复选择。
        available = list(frontiers)
        decisions: list[AssignmentDecision] = []

        # occupied 包含当前车辆位置和未完成任务目标。
        # 对 frontier 来说，这是一层兜底保护，主要避免目标点被重复占用。
        occupied = occupied_positions(snapshot)

        # 将地图 cells 转成按坐标索引的字典，便于快速统计 frontier 周围 UNKNOWN 数量。
        cell_map = {(cell["x"], cell["y"]): cell for cell in snapshot["map"]["cells"]}

        for vehicle in vehicles:
            start = vehicle["pose"]["position"]

            # 当前车辆自己的起点不能算作障碍，否则它会把自己所在格子堵住。
            blocked_positions = set(occupied)
            blocked_positions.discard(point_tuple(start))

            # 为当前空闲车辆选择最近且可达、仍有探索收益的 frontier。
            selected = self.nearest_reachable_frontier(
                snapshot["map"],
                start,
                available,
                blocked_positions,
                cell_map,
                scan_radius,
            )
            if selected is None:
                continue

            frontier = selected["frontier"]

            # score 取负距离：路径距离越短，score 越大，便于统一按“分数高更好”理解。
            decisions.append(
                AssignmentDecision(
                    vehicle_id=vehicle["vehicleId"],
                    frontier_id=frontier["frontierId"],
                    score=-float(selected["distance"]),
                )
            )

            # 一个 frontier 只分配给一辆车；同时把目标点加入 occupied，避免后续车辆再选。
            available = [item for item in available if item["frontierId"] != frontier["frontierId"]]
            occupied.add(point_tuple(frontier["position"]))
            if not available:
                break

        return decisions

    def nearest_reachable_frontier(
        self,
        map_grid: dict[str, Any],
        start: dict[str, int],
        frontiers: list[dict[str, Any]],
        occupied: set[tuple[int, int]],
        cell_map: dict[tuple[int, int], dict[str, Any]],
        scan_radius: int,
    ) -> dict[str, Any] | None:
        """从候选 frontier 中选出最近且可达的一个；不可达或无探索收益则跳过。"""
        reachable: list[dict[str, Any]] = []

        # 计算从车辆当前位置到所有可达格子的最短路径代价。
        # 这里用真实网格路径距离，而不是欧氏距离或曼哈顿距离，因此会考虑障碍物绕行。
        distances = shortest_path_distances(map_grid, start)
        for frontier in frontiers:
            position = frontier["position"]
            position_key = point_tuple(position)

            # 已被车辆或未完成任务占用的目标点不再作为候选。
            if position_key in occupied:
                continue

            # frontier 周围如果没有 UNKNOWN 格子，说明继续去这里没有探索收益。
            if unknown_cells_visible_from(position, cell_map, scan_radius) <= 0:
                continue

            # distances 中没有该点，表示从当前车辆位置无法到达。
            distance = distances.get(position_key)
            if distance is None:
                continue

            reachable.append(
                {
                    "frontier": frontier,
                    "distance": distance,
                    # manhattan 只作为距离相同时的稳定排序依据，不是主要选择标准。
                    "manhattan": manhattan(start, position),
                }
            )

        if not reachable:
            return None

        # 先按真实路径距离排序；若路径距离相同，再按曼哈顿距离做次级排序。
        reachable.sort(key=lambda item: (item["distance"], item["manhattan"]))
        return {
            "frontier": reachable[0]["frontier"],
            "distance": reachable[0]["distance"],
        }
