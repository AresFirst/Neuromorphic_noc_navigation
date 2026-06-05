"""Replanning policy for the closed-loop demo."""

from __future__ import annotations

import networkx as nx


class ReplanningPolicy:
    def __init__(
        self,
        replan_interval: int = 5,
        replan_on_congestion_on_route: bool = True,
        replan_on_blocked_edge: bool = True,
    ):
        self.replan_interval = max(1, int(replan_interval))
        self.replan_on_congestion_on_route = bool(replan_on_congestion_on_route)
        self.replan_on_blocked_edge = bool(replan_on_blocked_edge)

    def _future_edges(self, vehicle_state: dict, current_route: list[int]) -> list[tuple[int, int]]:
        route = [int(node) for node in current_route]
        if len(route) < 2:
            return []

        route_index = vehicle_state.get("route_index")
        if route_index is None:
            current_node = vehicle_state.get("current_node")
            if current_node in route:
                route_index = route.index(current_node)
            else:
                route_index = 0

        try:
            route_index = int(route_index)
        except (TypeError, ValueError):
            route_index = 0
        route_index = max(0, min(route_index, len(route) - 1))
        return list(zip(route[route_index:], route[route_index + 1 :]))

    def should_replan(
        self,
        step: int,
        vehicle_state: dict,
        current_route: list[int],
        active_congested_edges: list[tuple[int, int]],
        graph: nx.DiGraph,
    ) -> tuple[bool, str]:
        if bool(vehicle_state.get("arrived")):
            return False, "arrived"

        if step == 0:
            return True, "initial_plan"

        if not current_route or len(current_route) < 2:
            return True, "invalid_route"

        future_edges = self._future_edges(vehicle_state, current_route)
        if not future_edges:
            return True, "invalid_route"

        if self.replan_on_blocked_edge:
            for u, v in future_edges:
                if graph.has_edge(u, v) and graph[u][v].get("state") == "blocked":
                    return True, "blocked_edge_on_route"

        if self.replan_on_congestion_on_route:
            active_edges = {tuple(edge) for edge in active_congested_edges}
            for u, v in future_edges:
                if (u, v) in active_edges:
                    return True, "congested_edge_on_route"
                if graph.has_node(v):
                    penalty = graph.nodes[v].get("threshold_penalty")
                    if penalty not in (None, 0, 0.0):
                        return True, "threshold_penalty_on_route"

        if self.replan_interval > 0 and step % self.replan_interval == 0:
            return True, "replan_interval"

        return False, "no_replan"
