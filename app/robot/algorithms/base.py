from __future__ import annotations

from typing import Protocol


class FrontierScanProtocol(Protocol):
    def scan_and_upload(self, vehicle_id: str, *, detect_frontiers: bool | None = None) -> None:
        ...

    def detect_frontiers(self, vehicle_id: str, center: dict[str, int], radius: int) -> None:
        ...

    def unknown_cells_visible_from(self, position, cell_map) -> int:
        ...


class LowLevelMotionProtocol(Protocol):
    enabled: bool

    def run_once(self) -> None:
        ...

    def choose_step(self, vehicle, snapshot, *, selected_next, selected_edges):
        ...
