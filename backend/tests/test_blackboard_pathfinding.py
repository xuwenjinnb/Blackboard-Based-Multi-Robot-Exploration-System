import sys
import copy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.redis import Blackboard, now_ms
from app.config import SimulationConfig
from app.navigator import NavigatorComponent
from app.navigator.planners.astar_planner import astar
from app.navigator.planners.cbs_planner import CBSPlanner
from app.navigator.planners.st_astar_planner import st_astar
from app.controller.policies import (
    AssignmentDecision,
    NearestReachableFrontierPolicy,
    create_assignment_policy,
)
from app.simulation import SimulationEngine
from app.controller.policies.helpers import unknown_cells_visible_from
from app.visibility import has_line_of_sight


def test_blackboard_initializes_map_and_snapshot():
    board = Blackboard(width=8, height=6)
    snapshot = board.snapshot()

    assert snapshot["map"]["width"] == 8
    assert snapshot["map"]["height"] == 6
    assert snapshot["map"]["chunkSize"] == 10
    assert len(snapshot["map"]["cells"]) == 48
    assert "chunks" not in snapshot["map"]
    assert snapshot["systemStatus"] == "STOPPED"


def test_random_obstacles_redeploy_requested_vehicle_count_on_free_cells():
    board = Blackboard()
    simulation = SimulationEngine(board)
    simulation.configure_vehicle_deployment(count=5, mode="random")

    simulation.configure_obstacles(mode="random", density=0.5, seed=7)

    snapshot = board.snapshot()
    positions = {
        (
            vehicle["pose"]["position"]["x"],
            vehicle["pose"]["position"]["y"],
        )
        for vehicle in snapshot["vehicles"]
    }
    assert len(snapshot["vehicles"]) == 5
    assert len(positions) == 5
    assert positions.isdisjoint(board.true_obstacles)


def test_random_obstacles_accept_requested_count_and_keep_free_space_connected():
    board = Blackboard(width=12, height=10)
    requested = 25

    result = board.configure_obstacles(mode="random", count=requested, seed=11)

    assert result["count"] == requested
    assert len(board.true_obstacles) == requested
    free = {
        (x, y)
        for y in range(board.height)
        for x in range(board.width)
        if (x, y) not in board.true_obstacles
    }
    assert free
    reachable = {next(iter(free))}
    frontier = list(reachable)
    while frontier:
        point = frontier.pop()
        for neighbor in board._neighbors4(point):
            if neighbor in free and neighbor not in reachable:
                reachable.add(neighbor)
                frontier.append(neighbor)

    assert reachable == free


def test_random_obstacles_can_include_outer_ring():
    board = Blackboard(width=12, height=10)

    board.configure_obstacles(mode="random", count=35, seed=11)

    assert any(
        x in {0, board.width - 1} or y in {0, board.height - 1}
        for x, y in board.true_obstacles
    )


def test_random_obstacles_are_spread_out_when_space_allows():
    board = Blackboard(width=32, height=24)

    board.configure_obstacles(mode="random", count=120, seed=7)

    assert len(board.true_obstacles) == 120
    adjacent_pairs = sum(
        1
        for x, y in board.true_obstacles
        for neighbor in board._neighbors8((x, y))
        if neighbor in board.true_obstacles
    ) // 2
    assert adjacent_pairs == 0


def test_map_can_be_reconfigured_and_is_chunked():
    board = Blackboard(width=8, height=6, chunk_size=4)

    result = board.configure_map(width=10, height=7, chunk_size=3)
    snapshot = board.snapshot()

    assert result["width"] == 10
    assert result["height"] == 7
    assert result["chunkSize"] == 3
    assert snapshot["map"]["width"] == 10
    assert snapshot["map"]["height"] == 7
    assert snapshot["map"]["chunkSize"] == 3
    assert len(snapshot["map"]["cells"]) == 70
    assert result["chunks"] == 12
    assert "chunks" not in snapshot["map"]


def test_manual_obstacle_toggle_rejects_current_vehicle_position():
    board = Blackboard()
    simulation = SimulationEngine(board)
    simulation.configure_vehicle_deployment(count=4, mode="random")
    simulation.configure_obstacles(mode="manual")
    snapshot = board.snapshot()
    position = snapshot["vehicles"][0]["pose"]["position"]

    with pytest.raises(ValueError, match="occupied by a vehicle"):
        simulation.set_obstacle_at(position["x"], position["y"], True)

    assert (position["x"], position["y"]) not in board.true_obstacles


def test_batch_obstacle_brush_updates_cells_once():
    board = Blackboard(width=8, height=6)
    board.configure_obstacles(mode="manual")

    result = board.set_obstacles_at([
        {"x": 1, "y": 1, "blocked": True},
        {"x": 2, "y": 1, "blocked": True},
        {"x": 1, "y": 1, "blocked": False},
    ])

    assert result["cells"] == [
        {"x": 1, "y": 1, "blocked": True},
        {"x": 2, "y": 1, "blocked": True},
        {"x": 1, "y": 1, "blocked": False},
    ]
    assert board.true_obstacles == {(2, 1)}
    cell_map = {
        (cell["x"], cell["y"]): cell["state"]
        for cell in board.snapshot()["map"]["cells"]
    }
    assert cell_map[(1, 1)] == "UNKNOWN"
    assert cell_map[(2, 1)] == "OBSTACLE"


def test_vehicle_redeployment_clears_previous_visible_area():
    board = Blackboard()
    simulation = SimulationEngine(board)

    with board.batch():
        simulation.vehicle_deployment = {
            "mode": "random",
            "count": 1,
            "vehicles": [
                {
                    "vehicleId": "car-01",
                    "x": 2,
                    "y": 2,
                    "heading": 0,
                    "source": "RANDOM",
                    "adjusted": False,
                    "requested": None,
                }
            ],
        }
        simulation._reset_runtime_for_vehicle_deployment_locked()

    old_visible = {
        (cell["x"], cell["y"])
        for cell in board.snapshot()["map"]["cells"]
        if cell["state"] in {"FREE", "VISITED"}
    }
    assert old_visible

    with board.batch():
        simulation.vehicle_deployment = {
            "mode": "random",
            "count": 1,
            "vehicles": [
                {
                    "vehicleId": "car-01",
                    "x": 30,
                    "y": 21,
                    "heading": 180,
                    "source": "RANDOM",
                    "adjusted": False,
                    "requested": None,
                }
            ],
        }
        simulation._reset_runtime_for_vehicle_deployment_locked()

    cell_map = {
        (cell["x"], cell["y"]): cell
        for cell in board.snapshot()["map"]["cells"]
    }
    new_visible = {
        (cell["x"], cell["y"])
        for cell in cell_map.values()
        if cell["state"] in {"FREE", "VISITED"}
    }
    stale_visible = old_visible - new_visible

    assert stale_visible
    assert all(cell_map[point]["state"] == "UNKNOWN" for point in stale_visible)


def test_vehicle_scan_does_not_reveal_cells_behind_obstacle():
    board = Blackboard(width=7, height=5)
    simulation = SimulationEngine(board, config=SimulationConfig(scan_radius=3))
    board.true_obstacles = {(3, 2)}
    board.reset_perception_map_locked()
    board.register_vehicle("car-test", {"position": {"x": 1, "y": 2}, "heading": 0})

    simulation.scan_and_upload("car-test", detect_frontiers=False)

    cell_map = {
        (cell["x"], cell["y"]): cell["state"]
        for cell in board.snapshot()["map"]["cells"]
    }
    assert cell_map[(3, 2)] == "OBSTACLE"
    assert cell_map[(4, 2)] == "UNKNOWN"
    assert cell_map[(2, 1)] == "FREE"


def test_unknown_gain_excludes_cells_hidden_behind_obstacle():
    cell_map = {
        (x, y): {"x": x, "y": y, "state": "FREE"}
        for y in range(3)
        for x in range(5)
    }
    cell_map[(2, 1)]["state"] = "OBSTACLE"
    cell_map[(3, 1)]["state"] = "UNKNOWN"
    cell_map[(1, 2)]["state"] = "UNKNOWN"

    gain = unknown_cells_visible_from({"x": 1, "y": 1}, cell_map, scan_radius=3)

    assert gain == 1


def test_line_of_sight_cannot_leak_around_single_blocked_corner():
    obstacle = (2, 1)

    visible = has_line_of_sight(
        (1, 1),
        (3, 3),
        lambda point: point == obstacle,
    )

    assert visible is False


def test_vehicle_scan_does_not_reveal_diagonal_cells_around_wall_corner():
    board = Blackboard(width=6, height=6)
    simulation = SimulationEngine(board, config=SimulationConfig(scan_radius=3))
    board.true_obstacles = {(2, 1)}
    board.reset_perception_map_locked()
    board.register_vehicle("car-test", {"position": {"x": 1, "y": 1}, "heading": 0})

    simulation.scan_and_upload("car-test", detect_frontiers=False)

    cell_map = {
        (cell["x"], cell["y"]): cell["state"]
        for cell in board.snapshot()["map"]["cells"]
    }
    assert cell_map[(2, 1)] == "OBSTACLE"
    assert cell_map[(3, 3)] == "UNKNOWN"
    assert cell_map[(1, 3)] == "FREE"


@pytest.mark.parametrize("system_status", ["PAUSED", "STOPPED"])
def test_vehicle_reduction_removes_largest_ids_without_resetting_map(system_status):
    board = Blackboard()
    simulation = SimulationEngine(board)
    simulation.configure_vehicle_deployment(count=5, mode="random")
    before_ids = sorted(vehicle["vehicleId"] for vehicle in board.snapshot()["vehicles"])
    assert before_ids == ["car-01", "car-02", "car-03", "car-04", "car-05"]

    frontier = board.save_frontier(
        {"position": {"x": 1, "y": 1}, "unknownGain": 1, "discoveredBy": "test"}
    )
    task = board.create_task_for_frontier("car-05", frontier)
    request = board.create_navigation_request(task)
    board.write_navigation_plan(
        {
            "requestId": request["requestId"],
            "taskId": task["taskId"],
            "vehicleId": "car-05",
            "start": request["start"],
            "goal": request["goal"],
            "path": [],
            "status": "SUCCESS",
            "createdBy": "navigator-test",
        }
    )
    board.set_system_status(system_status)
    before = board.snapshot()
    before_visible = {
        (cell["x"], cell["y"])
        for cell in before["map"]["cells"]
        if cell["state"] in {"FREE", "VISITED"}
    }

    deployment = simulation.configure_vehicle_deployment(count=3, mode="random")

    snapshot = board.snapshot()
    after_ids = sorted(vehicle["vehicleId"] for vehicle in snapshot["vehicles"])
    after_visible = {
        (cell["x"], cell["y"])
        for cell in snapshot["map"]["cells"]
        if cell["state"] in {"FREE", "VISITED"}
    }
    assert after_ids == ["car-01", "car-02", "car-03"]
    assert deployment["mode"] == "count-adjust"
    assert deployment["count"] == 3
    assert snapshot["systemStatus"] == system_status
    assert snapshot["map"]["version"] == before["map"]["version"]
    assert before_visible <= after_visible
    assert all(task["vehicleId"] != "car-05" for task in snapshot["tasks"])
    assert all(request["vehicleId"] != "car-05" for request in snapshot["navigationRequests"])
    assert all(plan["vehicleId"] != "car-05" for plan in snapshot["navigationPlans"])
    assert board.frontiers[frontier["frontierId"]]["status"] == "OPEN"


@pytest.mark.parametrize("system_status", ["PAUSED", "STOPPED"])
def test_vehicle_increase_preserves_existing_vehicles_and_adds_next_ids(system_status):
    board = Blackboard()
    simulation = SimulationEngine(board)
    simulation.configure_vehicle_deployment(count=3, mode="random")
    board.set_system_status(system_status)
    before = board.snapshot()
    before_positions = {vehicle["vehicleId"]: dict(vehicle["pose"]["position"]) for vehicle in before["vehicles"]}
    before_map = copy.deepcopy(before["map"])

    deployment = simulation.configure_vehicle_deployment(count=5, mode="random")

    snapshot = board.snapshot()
    after_positions = {
        vehicle["vehicleId"]: vehicle["pose"]["position"]
        for vehicle in snapshot["vehicles"]
    }
    assert sorted(after_positions) == ["car-01", "car-02", "car-03", "car-04", "car-05"]
    assert deployment["count"] == 5
    assert snapshot["systemStatus"] == system_status
    assert snapshot["map"] == before_map
    for vehicle_id, position in before_positions.items():
        assert after_positions[vehicle_id] == position


def test_map_patch_updates_version_and_cells():
    board = Blackboard(width=8, height=6)
    before = board.snapshot()["map"]["version"]

    result = board.upload_map_patch(
        {
            "patchId": "patch-test",
            "vehicleId": "car-test",
            "baseMapVersion": before,
            "cells": [
                {"x": 2, "y": 2, "state": "FREE", "confidence": 1.0, "updatedAt": now_ms()},
                {"x": 3, "y": 2, "state": "OBSTACLE", "confidence": 1.0, "updatedAt": now_ms()},
            ],
            "timestamp": now_ms(),
        }
    )

    snapshot = board.snapshot()
    assert result["changed"] == 2
    assert snapshot["map"]["version"] == before + 1
    assert snapshot["map"]["cells"][2 * 8 + 2]["state"] == "FREE"
    assert snapshot["map"]["cells"][2 * 8 + 3]["state"] == "OBSTACLE"


def test_snapshot_since_returns_map_delta_without_full_cells():
    board = Blackboard(width=8, height=6, chunk_size=4)
    before = board.snapshot()["map"]["version"]

    board.upload_map_patch(
        {
            "vehicleId": "car-test",
            "cells": [
                {"x": 2, "y": 2, "state": "FREE", "confidence": 1.0, "updatedAt": now_ms()},
                {"x": 5, "y": 4, "state": "OBSTACLE", "confidence": 1.0, "updatedAt": now_ms()},
            ],
        }
    )

    snapshot = board.snapshot_since(before)

    assert "cells" not in snapshot["map"]
    assert "chunks" not in snapshot["map"]
    assert snapshot["mapDelta"]["fromVersion"] == before
    assert snapshot["mapDelta"]["toVersion"] == before + 1
    assert snapshot["mapDelta"]["generation"] == snapshot["map"]["generation"]
    assert snapshot["mapDelta"]["chunkIds"] == ["0:0", "1:1"]
    assert {
        (cell["x"], cell["y"], cell["state"])
        for cell in snapshot["mapDelta"]["cells"]
    } == {
        (2, 2, "FREE"),
        (5, 4, "OBSTACLE"),
    }


def test_snapshot_since_falls_back_to_full_snapshot_when_delta_is_unavailable():
    board = Blackboard(width=8, height=6)
    before = board.snapshot()["map"]["version"]
    board.upload_map_patch(
        {
            "vehicleId": "car-test",
            "cells": [{"x": 1, "y": 1, "state": "FREE"}],
        }
    )
    board._clear_map_delta_log_locked()

    snapshot = board.snapshot_since(before)

    assert "mapDelta" not in snapshot
    assert snapshot["map"]["cells"]
    assert "chunks" not in snapshot["map"]


def test_snapshot_since_falls_back_after_map_generation_changes():
    board = Blackboard(width=8, height=6)
    before = board.snapshot()["map"]

    board.configure_map(width=10, height=7, chunk_size=3)
    snapshot = board.snapshot_since(before["version"], before["generation"])

    assert "mapDelta" not in snapshot
    assert snapshot["map"]["width"] == 10
    assert snapshot["map"]["cells"]
    assert "chunks" not in snapshot["map"]


def test_frontier_is_saved_and_deduplicated():
    board = Blackboard(width=8, height=6)
    first = board.save_frontier(
        {
            "position": {"x": 3, "y": 3},
            "unknownGain": 5,
            "discoveredBy": "car-test",
            "status": "OPEN",
            "timestamp": now_ms(),
        }
    )
    second = board.save_frontier(
        {
            "position": {"x": 3, "y": 3},
            "unknownGain": 7,
            "discoveredBy": "car-test",
            "status": "OPEN",
            "timestamp": now_ms(),
        }
    )

    assert first["frontierId"] == second["frontierId"]
    assert second["unknownGain"] == 7
    assert "score" not in second
    assert len(board.snapshot()["frontiers"]) == 1


def test_frontier_hidden_behind_wall_corner_is_closed():
    board = Blackboard(width=5, height=4)
    for cell in board.map["cells"]:
        cell["state"] = "FREE"
        cell["confidence"] = 1.0
    board.cell_at(2, 1)["state"] = "OBSTACLE"
    board.cell_at(2, 2)["state"] = "UNKNOWN"
    frontier = board.save_frontier(
        {
            "position": {"x": 1, "y": 1},
            "unknownGain": 1,
            "discoveredBy": "car-test",
        }
    )

    closed = board.refresh_frontiers_locked(scan_radius=2)

    assert closed == 1
    assert board.frontiers[frontier["frontierId"]]["status"] == "CLOSED"
    assert board.frontiers[frontier["frontierId"]]["unknownGain"] == 0
    assert board.open_frontiers() == []


def test_controller_removes_frontiers_without_visible_unknown_gain():
    board = Blackboard(width=5, height=4)
    for cell in board.map["cells"]:
        cell["state"] = "FREE"
        cell["confidence"] = 1.0
    board.cell_at(2, 1)["state"] = "OBSTACLE"
    board.cell_at(2, 2)["state"] = "UNKNOWN"
    board.register_vehicle("car-test", {"position": {"x": 1, "y": 1}, "heading": 0})
    frontier = board.save_frontier(
        {
            "position": {"x": 1, "y": 1},
            "unknownGain": 1,
            "discoveredBy": "car-test",
        }
    )
    simulation = SimulationEngine(board)

    simulation.controller_phase()

    assert board.frontiers[frontier["frontierId"]]["status"] == "CLOSED"
    assert board.snapshot()["tasks"] == []


def test_closing_assigned_frontier_cancels_task_and_releases_vehicle():
    board = Blackboard(width=5, height=4)
    for cell in board.map["cells"]:
        cell["state"] = "FREE"
        cell["confidence"] = 1.0
    board.cell_at(2, 1)["state"] = "OBSTACLE"
    board.cell_at(2, 2)["state"] = "UNKNOWN"
    board.register_vehicle("car-test", {"position": {"x": 1, "y": 1}, "heading": 0})
    frontier = board.save_frontier(
        {
            "position": {"x": 1, "y": 1},
            "unknownGain": 1,
            "discoveredBy": "car-test",
        }
    )
    task = board.create_task_for_frontier("car-test", frontier)

    board.refresh_frontiers_locked(scan_radius=2)

    assert board.frontiers[frontier["frontierId"]]["status"] == "CLOSED"
    assert board.tasks[task["taskId"]]["status"] == "CANCELLED"
    assert board.vehicles["car-test"]["currentTaskId"] is None
    assert board.vehicles["car-test"]["status"] == "IDLE"


def test_failed_plan_closes_frontier_and_releases_vehicle():
    board = Blackboard(width=5, height=4)
    board.register_vehicle("car-test", {"position": {"x": 1, "y": 1}, "heading": 0})
    frontier = board.save_frontier(
        {
            "position": {"x": 3, "y": 1},
            "unknownGain": 1,
            "discoveredBy": "car-test",
        }
    )
    task = board.create_task_for_frontier("car-test", frontier)
    request = board.create_navigation_request(task)

    board.write_navigation_plan(
        {
            "requestId": request["requestId"],
            "taskId": task["taskId"],
            "vehicleId": "car-test",
            "status": "NO_PATH",
            "path": [],
            "failReason": "no path found",
            "createdBy": "navigator-test",
        }
    )

    assert board.tasks[task["taskId"]]["status"] == "FAILED"
    assert board.frontiers[frontier["frontierId"]]["status"] == "CLOSED"
    assert board.vehicles["car-test"]["currentTaskId"] is None
    assert board.open_frontiers() == []


def test_frontier_outside_map_is_rejected():
    board = Blackboard(width=8, height=6)

    with pytest.raises(ValueError, match="outside the map"):
        board.save_frontier(
            {
                "position": {"x": 8, "y": 3},
                "unknownGain": 1,
                "discoveredBy": "car-test",
            }
        )


def test_unchanged_map_patch_does_not_rewrite_frontier_state():
    board = Blackboard(width=8, height=6)
    board.register_vehicle("car-test", {"position": {"x": 2, "y": 2}, "heading": 0})
    board.frontiers["frontier-stale"] = {
        "frontierId": "frontier-stale",
        "position": {"x": 8, "y": 2},
        "unknownGain": 5,
        "discoveredBy": "car-test",
        "status": "OPEN",
        "timestamp": now_ms(),
    }
    before = board.snapshot()["map"]["version"]

    result = board.upload_map_patch(
        {
            "vehicleId": "car-test",
            "cells": [],
        }
    )

    assert result["changed"] == 0
    assert board.snapshot()["map"]["version"] == before
    assert board.frontiers["frontier-stale"]["status"] == "OPEN"
    assert board.open_frontiers() == []


def test_astar_returns_path_around_obstacle():
    cells = []
    for y in range(5):
        for x in range(7):
            state = "FREE"
            if x == 3 and y in {0, 1, 2, 3}:
                state = "OBSTACLE"
            cells.append(
                {
                    "x": x,
                    "y": y,
                    "state": state,
                    "confidence": 1,
                    "updatedAt": now_ms(),
                }
            )
    map_grid = {"width": 7, "height": 5, "cells": cells}

    path, reason = astar(map_grid, {"x": 1, "y": 1}, {"x": 5, "y": 1})

    assert reason is None
    assert path[0]["position"] == {"x": 1, "y": 1}
    assert path[-1]["position"] == {"x": 5, "y": 1}
    assert all(step["position"] != {"x": 3, "y": 1} for step in path)


def test_st_astar_waits_for_reserved_time_slot():
    cells = [
        {"x": x, "y": 0, "state": "FREE", "confidence": 1, "updatedAt": now_ms()}
        for x in range(3)
    ]
    map_grid = {"width": 3, "height": 1, "cells": cells}

    path, reason = st_astar(
        map_grid,
        {"x": 0, "y": 0},
        {"x": 2, "y": 0},
        reservations={1: {(1, 0)}},
        max_time=6,
    )

    assert reason is None
    assert path[1]["position"] == {"x": 0, "y": 0}
    assert path[1]["action"] == "WAIT"
    assert path[-1]["position"] == {"x": 2, "y": 0}


def test_st_astar_allows_start_reserved_at_time_zero():
    cells = [
        {"x": x, "y": 0, "state": "FREE", "confidence": 1, "updatedAt": now_ms()}
        for x in range(3)
    ]
    map_grid = {"width": 3, "height": 1, "cells": cells}

    path, reason = st_astar(
        map_grid,
        {"x": 0, "y": 0},
        {"x": 2, "y": 0},
        reservations={0: {(0, 0)}},
        max_time=6,
    )

    assert reason is None
    assert path[-1]["position"] == {"x": 2, "y": 0}


def test_frontiers_are_boundary_points():
    board = Blackboard(width=16, height=12)
    simulation = SimulationEngine(board)

    board.register_vehicle("car-test", {"position": {"x": 6, "y": 6}, "heading": 0})
    simulation.scan_and_upload("car-test")

    snapshot = board.snapshot()
    cell_map = {(cell["x"], cell["y"]): cell for cell in snapshot["map"]["cells"]}
    frontiers = snapshot["frontiers"]

    assert len(frontiers) > 0
    for frontier in frontiers:
        cell = cell_map[(frontier["position"]["x"], frontier["position"]["y"])]
        assert cell["state"] in {"FREE", "VISITED"}
        assert frontier["unknownGain"] > 0
        assert simulation.unknown_cells_visible_from(frontier["position"], cell_map) > 0
        x = frontier["position"]["x"]
        y = frontier["position"]["y"]
        neighbors = [
            (x + dx, y + dy)
            for dy in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if dx != 0 or dy != 0
        ]
        assert any(cell_map.get(point, {}).get("state") == "UNKNOWN" for point in neighbors)


def test_controller_uses_pluggable_assignment_policy():
    class FirstFrontierPolicy:
        name = "first-frontier"

        def __init__(self):
            self.called = False

        def select_assignments(self, snapshot, vehicles, frontiers, *, scan_radius):
            self.called = True
            if not vehicles or not frontiers:
                return []
            return [
                AssignmentDecision(
                    vehicle_id=vehicles[0]["vehicleId"],
                    frontier_id=frontiers[0]["frontierId"],
                    priority=9,
                )
            ]

    board = Blackboard()
    policy = FirstFrontierPolicy()
    simulation = SimulationEngine(board, assignment_policy=policy)
    simulation.ensure_demo_vehicles()

    simulation.controller_phase()

    snapshot = board.snapshot()
    assert policy.called
    assert any(task["status"] == "PENDING" for task in snapshot["tasks"])
    assert any(request["priority"] == 9 for request in snapshot["navigationRequests"])


def test_movement_steps_count_only_actual_vehicle_moves():
    board = Blackboard(width=5, height=5)
    for cell in board.map["cells"]:
        cell["state"] = "FREE"
    board.true_obstacles = set()
    board.register_vehicle("car-01", {"position": {"x": 1, "y": 1}, "heading": 0})
    frontier = board.save_frontier(
        {"position": {"x": 2, "y": 1}, "unknownGain": 1, "discoveredBy": "test"}
    )
    task = board.create_task_for_frontier("car-01", frontier)
    request = board.create_navigation_request(task)
    board.write_navigation_plan(
        {
            "requestId": request["requestId"],
            "taskId": task["taskId"],
            "vehicleId": "car-01",
            "start": {"x": 1, "y": 1},
            "goal": {"x": 2, "y": 1},
            "path": [
                {
                    "stepIndex": 0,
                    "position": {"x": 1, "y": 1},
                    "heading": 0,
                    "expectedTimeSlot": 0,
                    "action": "MOVE",
                },
                {
                    "stepIndex": 1,
                    "position": {"x": 1, "y": 1},
                    "heading": 0,
                    "expectedTimeSlot": 1,
                    "action": "WAIT",
                },
                {
                    "stepIndex": 2,
                    "position": {"x": 2, "y": 1},
                    "heading": 0,
                    "expectedTimeSlot": 2,
                    "action": "MOVE",
                },
            ],
            "status": "SUCCESS",
            "createdBy": "navigator-test",
        }
    )
    simulation = SimulationEngine(board)

    simulation.movement_steps += simulation.robot_phase()
    assert simulation.movement_steps == 0

    simulation.movement_steps += simulation.robot_phase()
    assert simulation.movement_steps == 1


def test_robot_phase_moves_all_planned_vehicles_in_one_tick():
    board = Blackboard(width=7, height=5)
    for cell in board.map["cells"]:
        cell["state"] = "FREE"
    board.true_obstacles = set()
    board.register_vehicle("car-01", {"position": {"x": 1, "y": 1}, "heading": 0})
    board.register_vehicle("car-02", {"position": {"x": 1, "y": 3}, "heading": 0})

    for vehicle_id, y in (("car-01", 1), ("car-02", 3)):
        frontier = board.save_frontier(
            {"position": {"x": 3, "y": y}, "unknownGain": 1, "discoveredBy": "test"}
        )
        task = board.create_task_for_frontier(vehicle_id, frontier)
        request = board.create_navigation_request(task)
        board.write_navigation_plan(
            {
                "requestId": request["requestId"],
                "taskId": task["taskId"],
                "vehicleId": vehicle_id,
                "start": {"x": 1, "y": y},
                "goal": {"x": 3, "y": y},
                "path": [
                    {
                        "stepIndex": 0,
                        "position": {"x": 1, "y": y},
                        "heading": 0,
                        "expectedTimeSlot": 0,
                        "action": "MOVE",
                    },
                    {
                        "stepIndex": 1,
                        "position": {"x": 2, "y": y},
                        "heading": 0,
                        "expectedTimeSlot": 1,
                        "action": "MOVE",
                    },
                    {
                        "stepIndex": 2,
                        "position": {"x": 3, "y": y},
                        "heading": 0,
                        "expectedTimeSlot": 2,
                        "action": "MOVE",
                    },
                ],
                "status": "SUCCESS",
                "createdBy": "navigator-test",
            }
        )

    simulation = SimulationEngine(board)

    assert simulation.robot_phase() == 2
    positions = {
        vehicle["vehicleId"]: vehicle["pose"]["position"]
        for vehicle in board.snapshot()["vehicles"]
    }
    assert positions == {
        "car-01": {"x": 2, "y": 1},
        "car-02": {"x": 2, "y": 3},
    }


def test_low_mdp_pauses_when_no_unknown_cells_remain():
    board = Blackboard(width=5, height=5)
    for cell in board.map["cells"]:
        cell["state"] = "FREE"
    board.true_obstacles = set()
    board.register_vehicle("car-01", {"position": {"x": 2, "y": 2}, "heading": 0})
    board.set_system_status("RUNNING")
    simulation = SimulationEngine(board, config=SimulationConfig(policy="low_mdp"))

    simulation.step()

    assert board.system_status == "PAUSED"
    assert any(event["type"] == "EXPLORATION_COMPLETE" for event in board.snapshot()["events"])


def test_nearest_reachable_policy_uses_path_distance_and_skips_occupied_targets():
    cells = []
    for y in range(5):
        for x in range(7):
            state = "FREE"
            if x == 2 and y in {0, 1, 2, 3}:
                state = "OBSTACLE"
            if (x, y) in {(4, 1), (6, 3)}:
                state = "UNKNOWN"
            cells.append({"x": x, "y": y, "state": state, "confidence": 1, "updatedAt": now_ms()})

    snapshot = {
        "map": {"width": 7, "height": 5, "cells": cells},
        "vehicles": [
            {"vehicleId": "car-01", "pose": {"position": {"x": 1, "y": 1}}},
            {"vehicleId": "car-02", "pose": {"position": {"x": 4, "y": 2}}},
        ],
        "tasks": [],
    }
    frontiers = [
        {"frontierId": "blocked-by-car", "position": {"x": 4, "y": 2}, "status": "OPEN"},
        {"frontierId": "near-by-path", "position": {"x": 3, "y": 1}, "status": "OPEN"},
        {"frontierId": "far-by-path", "position": {"x": 6, "y": 2}, "status": "OPEN"},
    ]

    decisions = NearestReachableFrontierPolicy().select_assignments(
        snapshot,
        [snapshot["vehicles"][0]],
        frontiers,
        scan_radius=1,
    )

    assert decisions
    assert decisions[0].frontier_id == "near-by-path"


def test_cbs_planner_resolves_vertex_and_edge_conflicts():
    cells = [
        {"x": x, "y": y, "state": "FREE", "confidence": 1, "updatedAt": now_ms()}
        for y in range(3)
        for x in range(5)
    ]
    snapshot = {
        "map": {"width": 5, "height": 3, "version": 1, "cells": cells},
        "vehicles": [
            {
                "vehicleId": "car-01",
                "currentTaskId": "task-01",
                "pose": {"position": {"x": 1, "y": 1}},
            },
            {
                "vehicleId": "car-02",
                "currentTaskId": "task-02",
                "pose": {"position": {"x": 3, "y": 1}},
            },
        ],
        "tasks": [
            {"taskId": "task-01", "vehicleId": "car-01", "status": "PENDING", "pathQueue": []},
            {"taskId": "task-02", "vehicleId": "car-02", "status": "PENDING", "pathQueue": []},
        ],
    }
    requests = [
        {
            "requestId": "request-01",
            "taskId": "task-01",
            "vehicleId": "car-01",
            "start": {"x": 1, "y": 1},
            "goal": {"x": 3, "y": 1},
        },
        {
            "requestId": "request-02",
            "taskId": "task-02",
            "vehicleId": "car-02",
            "start": {"x": 3, "y": 1},
            "goal": {"x": 1, "y": 1},
        },
    ]
    planner = CBSPlanner(SimulationConfig(navigator_algorithm="cbs"))

    results = planner.plan_batch(snapshot, requests)
    paths = {
        request["vehicleId"]: results[request["requestId"]][0]
        for request in requests
    }

    assert all(paths.values())
    assert planner.detect_conflict(paths) is None


def test_navigator_component_can_use_cbs_mode_for_pending_requests():
    board = Blackboard(width=5, height=3)
    for cell in board.map["cells"]:
        cell["state"] = "FREE"
    board.register_vehicle("car-01", {"position": {"x": 1, "y": 1}, "heading": 0})
    board.register_vehicle("car-02", {"position": {"x": 3, "y": 1}, "heading": 180})
    frontier_01 = board.save_frontier(
        {"position": {"x": 3, "y": 1}, "unknownGain": 1, "discoveredBy": "test"}
    )
    frontier_02 = board.save_frontier(
        {"position": {"x": 1, "y": 1}, "unknownGain": 1, "discoveredBy": "test"}
    )
    task_01 = board.create_task_for_frontier("car-01", frontier_01)
    task_02 = board.create_task_for_frontier("car-02", frontier_02)
    board.create_navigation_request(task_01)
    board.create_navigation_request(task_02)

    navigator = NavigatorComponent(
        board,
        SimulationConfig(navigator_algorithm="cbs"),
        ["navigator-test"],
    )
    navigator.run_once()
    snapshot = board.snapshot()
    plans = snapshot["navigationPlans"]
    paths = {plan["vehicleId"]: plan["path"] for plan in plans if plan["status"] == "SUCCESS"}

    assert len(plans) == 2
    assert all(plan.get("planner") == "cbs" for plan in plans)
    assert CBSPlanner(SimulationConfig(navigator_algorithm="cbs")).detect_conflict(paths) is None
