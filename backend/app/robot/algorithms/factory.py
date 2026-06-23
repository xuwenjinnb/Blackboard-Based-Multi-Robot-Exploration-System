from __future__ import annotations

from .frontier_scan import FrontierScanAlgorithm
from .low_mdp import LowLevelMDPAlgorithm
from ...redis import Blackboard
from ...config import SimulationConfig


def create_frontier_scan_algorithm(blackboard: Blackboard, config: SimulationConfig) -> FrontierScanAlgorithm:
    return FrontierScanAlgorithm(blackboard, config)


def create_low_level_mdp_algorithm(
    blackboard: Blackboard,
    config: SimulationConfig,
    scanner: FrontierScanAlgorithm,
) -> LowLevelMDPAlgorithm:
    return LowLevelMDPAlgorithm(blackboard, config, scanner)
