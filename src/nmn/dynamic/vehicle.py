"""Simple ego vehicle agent for route following."""

from __future__ import annotations

class EgoVehicle:
    def __init__(self, start_node: int, target_node: int, speed_edges_per_step: float = 1.0):
        self.start_node = int(start_node)
        self.target_node = int(target_node)
        self.speed_edges_per_step = float(speed_edges_per_step)
        self._route: list[int] = [int(start_node)]
        self._route_index = 0
        self._current_node = int(start_node)

    @property
    def route(self) -> list[int]:
        return list(self._route)

    @property
    def route_index(self) -> int:
        return int(self._route_index)

    def set_route(self, route: list[int]) -> None:
        route_list = [int(node) for node in route]
        self._route = route_list
        self._route_index = 0
        if route_list:
            self._current_node = route_list[0]

    def current_node(self) -> int:
        return int(self._current_node)

    def next_edge(self) -> tuple[int, int] | None:
        if not self._route or self._route_index >= len(self._route) - 1:
            return None
        return int(self._route[self._route_index]), int(self._route[self._route_index + 1])

    def has_arrived(self) -> bool:
        return self.current_node() == self.target_node

    def snapshot(self) -> dict:
        remaining_route = self._route[self._route_index :] if self._route else []
        return {
            "current_node": self.current_node(),
            "target_node": self.target_node,
            "route_index": int(self._route_index),
            "remaining_route": [int(node) for node in remaining_route],
            "arrived": self.has_arrived(),
        }

    def step(self) -> dict:
        if self._route and not self.has_arrived() and self._route_index < len(self._route) - 1:
            self._route_index += 1
            self._current_node = int(self._route[self._route_index])
        return self.snapshot()
