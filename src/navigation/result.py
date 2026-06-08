"""Standard navigation result data structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class WavefrontFrame:
    t: int
    active_nodes: list[int]
    active_edges: list[tuple[int, int]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NavigationResult:
    start_node: int
    goal_node: int
    path_nodes: list[int]
    path_edges: list[tuple[int, int]]
    wavefront_frames: list[WavefrontFrame] = field(default_factory=list)
    total_cost: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
