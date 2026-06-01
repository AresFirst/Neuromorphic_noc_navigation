from __future__ import annotations

import math


class PlaceCellLayer:
    def __init__(
        self,
        node_positions: dict[int, tuple[float, float]],
        sigma: float = 0.1,
    ):
        if sigma <= 0:
            raise ValueError("sigma must be positive")
        if not node_positions:
            raise ValueError("node_positions must not be empty")
        self.node_positions = {
            int(node): (float(position[0]), float(position[1]))
            for node, position in node_positions.items()
        }
        self.sigma = float(sigma)

    def activations(self, x: float, y: float) -> dict[int, float]:
        result: dict[int, float] = {}
        for node, (node_x, node_y) in self.node_positions.items():
            distance_sq = (float(x) - node_x) ** 2 + (float(y) - node_y) ** 2
            result[node] = math.exp(-distance_sq / (2.0 * self.sigma**2))
        return result

    def winner_take_all(self, x: float, y: float) -> int:
        activations = self.activations(x, y)
        return min(activations, key=lambda node: (-activations[node], node))
