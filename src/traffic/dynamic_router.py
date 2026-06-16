"""Online dynamic routing using only currently observable edge state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import networkx as nx

from .edge_state import edge_travel_time, route_eta
from .vehicle import Vehicle

RoutePlanner = Callable[[nx.DiGraph, int, int], Any]


def _routable_view(graph: nx.DiGraph) -> nx.DiGraph:
    return nx.subgraph_view(
        graph,
        filter_node=lambda node: not bool(graph.nodes[node].get("snn_neuron_closed", False)),
        filter_edge=lambda u, v: graph[u][v].get("state") != "blocked"
        and not bool(graph[u][v].get("snn_synapse_closed", False)),
    )


@dataclass(slots=True)
class RoutePlan:
    route: list[int]
    eta: float
    backend: str = "dynamic_shortest_path"
    raw_result: Any | None = None


@dataclass(frozen=True, slots=True)
class DynamicRouterConfig:
    eta_improvement_threshold: float = 0.15
    reroute_check_interval: float = 10.0
    min_reroute_interval: float = 30.0
    congestion_threshold: float = 0.80
    lookahead_distance: float = 500.0


@dataclass(slots=True)
class RerouteDecision:
    rerouted: bool
    reroute_time: float
    old_route_eta_before_reroute: float
    new_route_eta_after_reroute: float
    affected_edge_ids: list[tuple[int, int]]
    old_route: list[int]
    new_route: list[int]
    reason: str


class DynamicRouter:
    """Route the navigation vehicle without future traffic information."""

    def __init__(self, config: DynamicRouterConfig | None = None) -> None:
        self.config = config or DynamicRouterConfig()
        self.last_check_time = -1.0e9
        self.last_plan: RoutePlan | None = None

    def plan_route(
        self,
        graph: nx.DiGraph,
        source: int,
        destination: int,
        *,
        route_planner: RoutePlanner | None = None,
    ) -> RoutePlan:
        """Plan from source to destination using current graph edge attributes."""
        if route_planner is not None:
            raw_result = route_planner(graph, int(source), int(destination))
            route = [int(node) for node in getattr(raw_result, "path_nodes", [])]
            if route:
                eta = route_eta(graph, route, weight="travel_time")
                backend = str(getattr(raw_result, "metadata", {}).get("backend", "project_router"))
                self.last_plan = RoutePlan(route=route, eta=eta, backend=backend, raw_result=raw_result)
                return self.last_plan

        route = [
            int(node)
            for node in nx.shortest_path(
                _routable_view(graph),
                int(source),
                int(destination),
                weight="travel_time",
            )
        ]
        self.last_plan = RoutePlan(route=route, eta=route_eta(graph, route, weight="travel_time"))
        return self.last_plan

    def _remaining_route_from_edge_end(self, vehicle: Vehicle) -> list[int]:
        edge = vehicle.current_edge
        if edge is None:
            return [int(vehicle.current_node)]
        index = min(vehicle.current_edge_index + 1, len(vehicle.route) - 1)
        return [int(node) for node in vehicle.route[index:]]

    def _old_remaining_eta(self, graph: nx.DiGraph, vehicle: Vehicle) -> float:
        return route_eta(graph, self._remaining_route_from_edge_end(vehicle), weight="travel_time")

    def _reroute_planning_graph(self, graph: nx.DiGraph, vehicle: Vehicle) -> nx.DiGraph:
        edge = vehicle.current_edge
        if edge is None:
            return graph
        current_u, current_v = edge
        reverse_edge = (int(current_v), int(current_u))
        if not graph.has_edge(*reverse_edge):
            return graph
        return nx.subgraph_view(
            graph,
            filter_node=lambda node: True,
            filter_edge=lambda u, v: (int(u), int(v)) != reverse_edge,
        )

    def _lookahead_congested_edges(self, graph: nx.DiGraph, vehicle: Vehicle) -> list[tuple[int, int]]:
        edges: list[tuple[int, int]] = []
        distance_seen = 0.0
        for idx in range(vehicle.current_edge_index, max(vehicle.current_edge_index, len(vehicle.route) - 1)):
            if idx >= len(vehicle.route) - 1:
                break
            u = int(vehicle.route[idx])
            v = int(vehicle.route[idx + 1])
            if not graph.has_edge(u, v):
                continue
            attrs = graph[u][v]
            length = max(1.0, float(attrs.get("length", 1.0) or 1.0))
            if idx == vehicle.current_edge_index:
                length = max(0.0, length - float(vehicle.position_on_edge))
            congestion = float(attrs.get("congestion_level", attrs.get("traffic_congestion", 0.0)) or 0.0)
            if congestion > float(self.config.congestion_threshold):
                edges.append((u, v))
            distance_seen += length
            if distance_seen >= float(self.config.lookahead_distance):
                break
        return edges

    def maybe_reroute(
        self,
        graph: nx.DiGraph,
        vehicle: Vehicle,
        *,
        current_time: float,
        route_planner: RoutePlanner | None = None,
        force: bool = False,
    ) -> RerouteDecision | None:
        """Check current conditions and reroute only if current ETA improves enough."""
        if vehicle.arrived or vehicle.destination not in graph:
            return None
        if not force and current_time - self.last_check_time < float(self.config.reroute_check_interval):
            return None
        self.last_check_time = float(current_time)
        if not force and current_time - vehicle.last_reroute_time < float(self.config.min_reroute_interval):
            return None

        source = int(vehicle.current_edge_end)
        if source == vehicle.destination or source not in graph:
            return None

        old_route = self._remaining_route_from_edge_end(vehicle)
        old_eta = self._old_remaining_eta(graph, vehicle)
        affected_edges = self._lookahead_congested_edges(graph, vehicle)

        try:
            planning_graph = self._reroute_planning_graph(graph, vehicle)
            new_plan = self.plan_route(planning_graph, source, vehicle.destination, route_planner=route_planner)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return RerouteDecision(
                rerouted=False,
                reroute_time=float(current_time),
                old_route_eta_before_reroute=old_eta,
                new_route_eta_after_reroute=float("inf"),
                affected_edge_ids=affected_edges,
                old_route=old_route,
                new_route=[],
                reason="no_current_route_available",
            )

        if not new_plan.route or new_plan.route == old_route:
            return None

        improvement_ok = old_eta > new_plan.eta * (1.0 + float(self.config.eta_improvement_threshold))
        severe_ahead = bool(affected_edges)
        if not improvement_ok:
            return RerouteDecision(
                rerouted=False,
                reroute_time=float(current_time),
                old_route_eta_before_reroute=old_eta,
                new_route_eta_after_reroute=float(new_plan.eta),
                affected_edge_ids=affected_edges,
                old_route=old_route,
                new_route=new_plan.route,
                reason="severe_congestion_without_eta_improvement" if severe_ahead else "eta_improvement_too_small",
            )

        vehicle.replace_remaining_route(new_plan.route, current_time=float(current_time))
        return RerouteDecision(
            rerouted=True,
            reroute_time=float(current_time),
            old_route_eta_before_reroute=old_eta,
            new_route_eta_after_reroute=float(new_plan.eta),
            affected_edge_ids=affected_edges,
            old_route=old_route,
            new_route=new_plan.route,
            reason="lookahead_congestion" if severe_ahead else "eta_improvement",
        )

    def current_edge_remaining_eta(self, graph: nx.DiGraph, vehicle: Vehicle) -> float:
        """ETA to finish the current edge, using only current speed."""
        edge = vehicle.current_edge
        if edge is None or not graph.has_edge(*edge):
            return 0.0
        attrs = graph[edge[0]][edge[1]]
        length = max(1.0, float(attrs.get("length", 1.0) or 1.0))
        remaining = max(0.0, length - float(vehicle.position_on_edge))
        speed = max(0.1, float(attrs.get("current_speed", 1.0) or 1.0))
        return remaining / speed

    def full_remaining_eta(self, graph: nx.DiGraph, vehicle: Vehicle) -> float:
        """ETA including the rest of the current edge plus future route."""
        return self.current_edge_remaining_eta(graph, vehicle) + self._old_remaining_eta(graph, vehicle)
