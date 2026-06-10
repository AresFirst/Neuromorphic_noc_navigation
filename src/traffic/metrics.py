"""Metrics and baseline helpers for dynamic traffic simulation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import networkx as nx

from .dynamic_router import RerouteDecision
from .edge_state import route_eta
from .vehicle import Vehicle


@dataclass(slots=True)
class RerouteLog:
    old_route_eta_before_reroute: float
    new_route_eta_after_reroute: float
    reroute_time: float
    affected_edge_ids: list[tuple[int, int]]
    old_route: list[int]
    new_route: list[int]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SimulationMetrics:
    navigation_vehicle_travel_time: float | None = None
    number_of_reroutes: int = 0
    total_distance: float = 0.0
    average_network_speed: float = 0.0
    average_congestion_level: float = 0.0
    number_of_congested_edges: int = 0
    reroute_logs: list[RerouteLog] = field(default_factory=list)
    samples: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reroute_logs"] = [log.to_dict() for log in self.reroute_logs]
        return payload


class MetricsRecorder:
    """Incrementally record current observable network and navigation metrics."""

    def __init__(self) -> None:
        self.metrics = SimulationMetrics()

    def record_network(self, graph: nx.DiGraph) -> None:
        speeds = [float(attrs.get("current_speed", 0.0) or 0.0) for _u, _v, attrs in graph.edges(data=True)]
        congestion = [float(attrs.get("congestion_level", 0.0) or 0.0) for _u, _v, attrs in graph.edges(data=True)]
        congested = sum(1 for value in congestion if value >= 0.7)
        self.metrics.samples += 1
        n = float(self.metrics.samples)
        avg_speed = sum(speeds) / len(speeds) if speeds else 0.0
        avg_congestion = sum(congestion) / len(congestion) if congestion else 0.0
        self.metrics.average_network_speed = ((n - 1.0) * self.metrics.average_network_speed + avg_speed) / n
        self.metrics.average_congestion_level = ((n - 1.0) * self.metrics.average_congestion_level + avg_congestion) / n
        self.metrics.number_of_congested_edges = int(congested)

    def record_navigation_vehicle(self, vehicle: Vehicle | None) -> None:
        if vehicle is None:
            return
        self.metrics.total_distance = float(vehicle.total_distance)
        if vehicle.travel_time is not None:
            self.metrics.navigation_vehicle_travel_time = float(vehicle.travel_time)

    def record_reroute(self, decision: RerouteDecision | None) -> None:
        if decision is None:
            return
        if decision.rerouted:
            self.metrics.number_of_reroutes += 1
        self.metrics.reroute_logs.append(
            RerouteLog(
                old_route_eta_before_reroute=float(decision.old_route_eta_before_reroute),
                new_route_eta_after_reroute=float(decision.new_route_eta_after_reroute),
                reroute_time=float(decision.reroute_time),
                affected_edge_ids=[(int(u), int(v)) for u, v in decision.affected_edge_ids],
                old_route=[int(node) for node in decision.old_route],
                new_route=[int(node) for node in decision.new_route],
                reason=str(decision.reason),
            )
        )


def baseline_static_shortest_path(graph: nx.DiGraph, origin: int, destination: int) -> tuple[list[int], float]:
    """Plan once with free-flow time and never reroute."""
    route = [int(node) for node in nx.shortest_path(graph, int(origin), int(destination), weight="free_flow_time")]
    return route, route_eta(graph, route, weight="free_flow_time")


def baseline_dynamic_shortest_path(graph: nx.DiGraph, origin: int, destination: int) -> tuple[list[int], float]:
    """Plan with current travel_time. This is the non-SNN dynamic baseline."""
    route = [int(node) for node in nx.shortest_path(graph, int(origin), int(destination), weight="travel_time")]
    return route, route_eta(graph, route, weight="travel_time")


def compare_baselines(
    graph: nx.DiGraph,
    origin: int,
    destination: int,
    *,
    project_route: list[int] | None = None,
) -> dict[str, dict[str, float | int | list[int] | None]]:
    """Return comparable static/dynamic/project-router route snapshots."""
    result: dict[str, dict[str, float | int | list[int] | None]] = {}
    try:
        route, eta = baseline_static_shortest_path(graph, origin, destination)
        result["static_shortest_path"] = {"route": route, "eta": eta, "path_nodes": len(route)}
    except Exception:
        result["static_shortest_path"] = {"route": [], "eta": None, "path_nodes": 0}

    try:
        route, eta = baseline_dynamic_shortest_path(graph, origin, destination)
        result["dynamic_shortest_path"] = {"route": route, "eta": eta, "path_nodes": len(route)}
    except Exception:
        result["dynamic_shortest_path"] = {"route": [], "eta": None, "path_nodes": 0}

    if project_route:
        result["project_router"] = {
            "route": [int(node) for node in project_route],
            "eta": route_eta(graph, [int(node) for node in project_route], weight="travel_time"),
            "path_nodes": len(project_route),
        }
    else:
        result["project_router"] = {"route": [], "eta": None, "path_nodes": 0}
    return result
