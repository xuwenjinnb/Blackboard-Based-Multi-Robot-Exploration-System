from app.redis import Blackboard
from app.config import SimulationConfig
from app.controller.policies import create_assignment_policy
from app.navigator.planners.astar_planner import astar
from app.pathfinding import shortest_path_distances
from app.simulation import SimulationEngine


def build_large_engine() -> tuple[Blackboard, SimulationEngine]:
    board = Blackboard(width=50, height=50, chunk_size=10)
    config = SimulationConfig(num_vehicles=8)
    engine = SimulationEngine(
        board,
        assignment_policy=create_assignment_policy("nearest"),
        config=config,
    )
    engine.configure_vehicle_deployment(count=8, mode="random")
    return board, engine


def test_large_layout_has_2500_cells_and_eight_vehicles() -> None:
    board, _ = build_large_engine()
    snapshot = board.snapshot()

    assert snapshot["map"]["width"] == 50
    assert snapshot["map"]["height"] == 50
    assert len(snapshot["map"]["cells"]) == 2500
    assert "chunks" not in snapshot["map"]
    assert len(snapshot["vehicles"]) == 8


def test_large_layout_returns_map_delta_after_scans() -> None:
    board, engine = build_large_engine()
    before = board.snapshot()

    for vehicle in before["vehicles"]:
        engine.scan_and_upload(vehicle["vehicleId"])

    after = board.snapshot_since(
        before["map"]["version"],
        before["map"]["generation"],
    )
    assert "mapDelta" in after
    assert "cells" not in after["map"]
    assert after["mapDelta"]["toVersion"] >= before["map"]["version"]


def test_distance_map_matches_astar_cost_on_known_grid() -> None:
    board = Blackboard(width=10, height=10, chunk_size=5)
    board.configure_obstacles(
        mode="custom",
        obstacles=[{"x": 4, "y": y} for y in range(1, 8) if y != 5],
    )
    board.upload_map_patch(
        {
            "vehicleId": "test",
            "cells": [
                {"x": x, "y": y, "state": "FREE", "confidence": 1.0}
                for y in range(10)
                for x in range(10)
                if (x, y) not in board.true_obstacles
            ],
        }
    )
    snapshot = board.snapshot()
    start = {"x": 2, "y": 2}
    goal = {"x": 7, "y": 7}
    path, reason = astar(snapshot["map"], start, goal)
    distances = shortest_path_distances(snapshot["map"], start)

    assert reason is None
    assert path
    assert distances[(goal["x"], goal["y"])] == len(path) - 1
