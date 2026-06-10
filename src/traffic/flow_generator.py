"""Runtime background vehicle demand generation."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import networkx as nx

from .vehicle import Vehicle


@dataclass(frozen=True, slots=True)
class FlowGeneratorConfig:
    traffic_mode: str = "normal"
    base_rate_veh_per_minute: float = 12.0
    min_od_distance_m: float = 600.0
    background_reroute_fraction: float = 0.30
    random_seed: int = 7
    peak_period_seconds: float = 900.0


class FlowGenerator:
    """Generate only current-time vehicle demand.

    该生成器不会预先创建整段仿真的车辆，也不会暴露未来 OD 需求。
    每次 ``generate`` 只根据当前时间和当前图状态创建当前 timestep 的新车。
    """

    def __init__(self, config: FlowGeneratorConfig | None = None) -> None:
        self.config = config or FlowGeneratorConfig()
        self.rng = random.Random(self.config.random_seed)
        self._counter = 0

    def _rate_at(self, current_time: float) -> float:
        mode = self.config.traffic_mode
        base = max(0.0, float(self.config.base_rate_veh_per_minute))
        if mode == "peak":
            period = max(60.0, float(self.config.peak_period_seconds))
            phase = (float(current_time) % period) / period
            return base * (0.35 + 1.85 * math.sin(math.pi * phase))
        if mode == "incident":
            return base * 1.15
        return base

    def _candidate_nodes(self, graph: nx.DiGraph) -> list[int]:
        return [
            int(node)
            for node in graph.nodes()
            if graph.out_degree(node) > 0 and graph.in_degree(node) > 0
        ]

    def _node_distance_m(self, graph: nx.DiGraph, source: int, target: int) -> float:
        source_attrs = graph.nodes[source]
        target_attrs = graph.nodes[target]
        # 小 bbox 内用经纬度近似即可；111_000 m 约等于 1 度纬度。
        dx = (float(source_attrs["lon"]) - float(target_attrs["lon"])) * 111_000.0
        dy = (float(source_attrs["lat"]) - float(target_attrs["lat"])) * 111_000.0
        return float(math.hypot(dx, dy))

    def _sample_od(self, graph: nx.DiGraph) -> tuple[int, int] | None:
        nodes = self._candidate_nodes(graph)
        if len(nodes) < 2:
            return None
        for _attempt in range(40):
            origin = int(self.rng.choice(nodes))
            destination = int(self.rng.choice(nodes))
            if origin == destination:
                continue
            if self._node_distance_m(graph, origin, destination) < float(self.config.min_od_distance_m):
                continue
            if nx.has_path(graph, origin, destination):
                return origin, destination
        return None

    def _route(self, graph: nx.DiGraph, origin: int, destination: int) -> list[int]:
        return [int(node) for node in nx.shortest_path(graph, origin, destination, weight="travel_time")]

    def generate(self, graph: nx.DiGraph, *, current_time: float, dt: float) -> list[Vehicle]:
        """Generate background vehicles for the current timestep."""
        expected = self._rate_at(current_time) * max(0.0, float(dt)) / 60.0
        count = int(expected)
        if self.rng.random() < expected - count:
            count += 1

        vehicles: list[Vehicle] = []
        for _ in range(count):
            od = self._sample_od(graph)
            if od is None:
                continue
            origin, destination = od
            try:
                route = self._route(graph, origin, destination)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue
            self._counter += 1
            vehicles.append(
                Vehicle(
                    vehicle_id=f"bg-{self._counter}",
                    origin=origin,
                    destination=destination,
                    departure_time=float(current_time),
                    route=route,
                    is_background_vehicle=True,
                    allow_reroute=self.rng.random() < float(self.config.background_reroute_fraction),
                )
            )
        return vehicles
