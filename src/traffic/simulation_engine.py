"""Main loop for runtime road-edge traffic simulation."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import networkx as nx

from navigation import NavigationResult

from .dynamic_router import DynamicRouter, DynamicRouterConfig, RerouteDecision, RoutePlanner
from .edge_state import initialize_edge_state, route_eta
from .flow_generator import FlowGenerator, FlowGeneratorConfig
from .incident_generator import IncidentGenerator, IncidentGeneratorConfig, TrafficIncident
from .metrics import MetricsRecorder, compare_baselines
from .state import TrafficEdgeState, TrafficSnapshot
from .traffic_state_updater import TrafficStateUpdater, TrafficStateUpdaterConfig
from .vehicle import Vehicle, make_navigation_vehicle
from .vehicle_simulator import VehicleSimulator, VehicleSimulatorConfig


@dataclass(frozen=True, slots=True)
class SimulationEngineConfig:
    dt: float = 5.0
    simulation_duration: float = 600.0
    random_seed: int = 7
    flow: FlowGeneratorConfig | None = None
    incidents: IncidentGeneratorConfig | None = None
    updater: TrafficStateUpdaterConfig | None = None
    vehicle_simulator: VehicleSimulatorConfig | None = None
    router: DynamicRouterConfig | None = None
    first_route_congestion_distance_m: float | None = None
    route_congestion_interval_m: float = 5_000.0
    route_congestion_target_count: int | None = None
    max_route_congestion_events: int = 10
    route_congestion_edge_count: int = 2
    route_congestion_lookahead_m: float = 1_000.0
    route_congestion_duration_seconds: float = 600.0
    route_congestion_capacity_multiplier: float = 0.01
    route_congestion_speed_multiplier: float = 0.01


@dataclass(slots=True)
class SimulationStepResult:
    current_time: float
    generated_vehicle_count: int
    total_vehicle_count: int
    active_incidents: list[TrafficIncident]
    reroute_decision: RerouteDecision | None
    metrics: dict[str, Any]


class SimulationEngine:
    """Run dynamic traffic without precomputing future congestion."""

    def __init__(self, base_graph: nx.DiGraph, config: SimulationEngineConfig | None = None) -> None:
        self.config = config or SimulationEngineConfig()
        flow_config = self.config.flow or FlowGeneratorConfig(random_seed=self.config.random_seed)
        incident_config = self.config.incidents or IncidentGeneratorConfig(random_seed=self.config.random_seed + 1)
        self.graph = initialize_edge_state(base_graph.copy(), current_time=0.0)
        self.current_time = 0.0
        self.flow_generator = FlowGenerator(flow_config)
        self.incident_generator = IncidentGenerator(incident_config)
        self.vehicle_simulator = VehicleSimulator(self.config.vehicle_simulator)
        self.state_updater = TrafficStateUpdater(self.config.updater)
        self.dynamic_router = DynamicRouter(self.config.router)
        self.metrics = MetricsRecorder()
        self.background_vehicles: list[Vehicle] = []
        self.navigation_vehicle: Vehicle | None = None
        self.navigation_result: NavigationResult | None = None
        self.previous_navigation_route: list[int] = []
        self.last_reroute_decision: RerouteDecision | None = None
        self.rng = random.Random(self.config.random_seed)
        self.next_route_congestion_distance = float(
            self.config.first_route_congestion_distance_m
            if self.config.first_route_congestion_distance_m is not None
            else self.config.route_congestion_interval_m
        )
        self.route_congestion_interval_runtime_m = float(self.config.route_congestion_interval_m)
        self.route_congestion_counter = 0
        self.routing_runtime_totals = {"snn": 0.0, "dijkstra": 0.0, "astar": 0.0}
        self.routing_event_count = 0

    def _route_length_m(self, route: list[int]) -> float:
        total = 0.0
        for u, v in zip(route, route[1:]):
            if self.graph.has_edge(int(u), int(v)):
                total += max(1.0, float(self.graph[int(u)][int(v)].get("length", 1.0) or 1.0))
        return float(total)

    def _reset_navigation_runtime_state(self, route: list[int] | None = None) -> None:
        self.previous_navigation_route = []
        self.last_reroute_decision = None
        interval = float(self.config.route_congestion_interval_m)
        first_distance = self.config.first_route_congestion_distance_m
        target_count = self.config.route_congestion_target_count
        if route and target_count is not None and int(target_count) > 0:
            route_length = self._route_length_m(route)
            interval = max(1.0, route_length / float(int(target_count) + 1))
            first_distance = interval
        self.route_congestion_interval_runtime_m = float(interval)
        self.next_route_congestion_distance = float(first_distance if first_distance is not None else interval)
        self.route_congestion_counter = 0
        self.routing_runtime_totals = {"snn": 0.0, "dijkstra": 0.0, "astar": 0.0}
        self.routing_event_count = 0

    @property
    def vehicles(self) -> list[Vehicle]:
        vehicles = list(self.background_vehicles)
        if self.navigation_vehicle is not None and not self.navigation_vehicle.arrived:
            vehicles.append(self.navigation_vehicle)
        return vehicles

    def _result_from_route(self, route: list[int], *, backend: str = "dynamic_shortest_path") -> NavigationResult:
        path_edges = [(int(u), int(v)) for u, v in zip(route, route[1:])]
        eta = route_eta(self.graph, route, weight="travel_time")
        length = 0.0
        for u, v in path_edges:
            if self.graph.has_edge(u, v):
                length += float(self.graph[u][v].get("length", 0.0) or 0.0)
        return NavigationResult(
            start_node=int(route[0]) if route else -1,
            goal_node=int(route[-1]) if route else -1,
            path_nodes=[int(node) for node in route],
            path_edges=path_edges,
            wavefront_frames=[],
            total_cost=float(eta),
            metadata={
                "success": bool(route),
                "backend": backend,
                "target_arrival_time_ms": None,
                "path_length_m": float(length),
                "path_travel_time_s": float(eta),
                "snn_runtime_sec": 0.0,
                "dynamic_sim_time": float(self.current_time),
            },
        )

    def _record_routing_runtime(self, result: NavigationResult | None) -> None:
        if result is None:
            return
        self.routing_event_count += 1
        self.routing_runtime_totals["snn"] += float(result.metadata.get("snn_runtime_sec", 0.0) or 0.0)
        benchmarks = result.metadata.get("algorithm_benchmarks") or {}
        if isinstance(benchmarks, dict):
            for key in ("dijkstra", "astar"):
                payload = benchmarks.get(key) or {}
                if isinstance(payload, dict):
                    self.routing_runtime_totals[key] += float(payload.get("runtime_sec", 0.0) or 0.0)
        result.metadata["routing_runtime_totals"] = {
            key: float(value) for key, value in self.routing_runtime_totals.items()
        }
        result.metadata["routing_event_count"] = int(self.routing_event_count)

    def _candidate_route_congestion_edges(self) -> list[tuple[int, int]]:
        vehicle = self.navigation_vehicle
        if vehicle is None or vehicle.arrived or len(vehicle.route) < 2:
            return []
        # Avoid closing the edge the vehicle is currently traversing; close one
        # or two upcoming synapses so the next pulse starts from the current node.
        start_idx = min(vehicle.current_edge_index + 1, max(0, len(vehicle.route) - 2))
        source = int(vehicle.current_edge_end)
        destination = int(vehicle.destination)

        def closure_keeps_destination_reachable(edge: tuple[int, int]) -> bool:
            if source not in self.graph or destination not in self.graph:
                return False
            blocked_edge = (int(edge[0]), int(edge[1]))
            view = nx.subgraph_view(
                self.graph,
                filter_node=lambda node: not bool(self.graph.nodes[node].get("snn_neuron_closed", False)),
                filter_edge=lambda u, v: (
                    (int(u), int(v)) != blocked_edge
                    and self.graph[u][v].get("state") != "blocked"
                    and not bool(self.graph[u][v].get("snn_synapse_closed", False))
                ),
            )
            try:
                return nx.has_path(view, source, destination)
            except (nx.NetworkXError, nx.NodeNotFound):
                return False

        candidates: list[tuple[int, int]] = []
        distance_seen = 0.0
        lookahead_m = max(1.0, float(self.config.route_congestion_lookahead_m))
        for idx in range(start_idx, len(vehicle.route) - 1):
            edge = (int(vehicle.route[idx]), int(vehicle.route[idx + 1]))
            if edge[1] == vehicle.destination:
                continue
            if self.graph.has_edge(*edge) and closure_keeps_destination_reachable(edge):
                candidates.append(edge)
                distance_seen += max(1.0, float(self.graph[edge[0]][edge[1]].get("length", 1.0) or 1.0))
            if distance_seen >= lookahead_m:
                break
        far_candidates: list[tuple[int, int]] = []
        far_distance_seen = 0.0
        min_pick_distance = min(max(100.0, lookahead_m * 0.35), max(100.0, lookahead_m - 500.0))
        for idx in range(start_idx, len(vehicle.route) - 1):
            edge = (int(vehicle.route[idx]), int(vehicle.route[idx + 1]))
            if (
                edge[1] == vehicle.destination
                or not self.graph.has_edge(*edge)
                or not closure_keeps_destination_reachable(edge)
            ):
                continue
            far_distance_seen += max(1.0, float(self.graph[edge[0]][edge[1]].get("length", 1.0) or 1.0))
            if far_distance_seen >= min_pick_distance:
                far_candidates.append(edge)
            if far_distance_seen >= lookahead_m:
                break
        if far_candidates:
            candidates = far_candidates
        self.rng.shuffle(candidates)
        return candidates[: max(1, int(self.config.route_congestion_edge_count))]

    def _maybe_trigger_route_congestion(self, current_time: float) -> list[TrafficIncident]:
        vehicle = self.navigation_vehicle
        if vehicle is None or vehicle.arrived:
            return []
        max_events = max(0, int(self.config.max_route_congestion_events))
        if self.config.route_congestion_target_count is not None:
            max_events = min(max_events, max(0, int(self.config.route_congestion_target_count)))
        if max_events <= 0 or self.route_congestion_counter >= max_events:
            return []
        interval = max(1.0, float(self.route_congestion_interval_runtime_m))
        triggered: list[TrafficIncident] = []
        while (
            float(vehicle.total_distance) >= float(self.next_route_congestion_distance)
            and self.route_congestion_counter < max_events
        ):
            affected_edges = self._candidate_route_congestion_edges()
            self.next_route_congestion_distance += interval
            if not affected_edges:
                continue
            self.route_congestion_counter += 1
            incident = TrafficIncident(
                event_id=f"route-congestion-{self.route_congestion_counter}",
                event_type="route_congestion",
                affected_edges=affected_edges,
                start_time=float(current_time),
                end_time=float(current_time + float(self.config.route_congestion_duration_seconds)),
                capacity_multiplier=float(self.config.route_congestion_capacity_multiplier),
                speed_multiplier=float(self.config.route_congestion_speed_multiplier),
                is_active=True,
            )
            self.incident_generator.incidents.append(incident)
            triggered.append(incident)
        return triggered

    def start_navigation(
        self,
        origin: int,
        destination: int,
        *,
        route_planner: RoutePlanner | None = None,
    ) -> NavigationResult:
        """Create the navigation vehicle using only the current edge state."""
        plan = self.dynamic_router.plan_route(
            self.graph,
            int(origin),
            int(destination),
            route_planner=route_planner,
        )
        self.navigation_vehicle = make_navigation_vehicle(
            "nav-1",
            int(origin),
            int(destination),
            plan.route,
            self.current_time,
        )
        self._reset_navigation_runtime_state(plan.route)
        self.navigation_result = plan.raw_result if isinstance(plan.raw_result, NavigationResult) else self._result_from_route(
            plan.route,
            backend=plan.backend,
        )
        return self.navigation_result

    def start_navigation_from_result(self, result: NavigationResult) -> NavigationResult:
        """Start driving on an already planned route without recomputing it."""
        if not result.path_nodes:
            raise ValueError("cannot start navigation from an empty route")
        self.navigation_vehicle = make_navigation_vehicle(
            "nav-1",
            int(result.start_node),
            int(result.goal_node),
            [int(node) for node in result.path_nodes],
            self.current_time,
        )
        self._reset_navigation_runtime_state(result.path_nodes)
        self.navigation_result = result
        return result

    def update_config(self, config: SimulationEngineConfig) -> None:
        """Apply new runtime parameters without resetting current vehicles/events."""
        self.config = config
        self.flow_generator.config = config.flow or FlowGeneratorConfig(random_seed=config.random_seed)
        self.incident_generator.config = config.incidents or IncidentGeneratorConfig(random_seed=config.random_seed + 1)
        self.vehicle_simulator.config = config.vehicle_simulator or VehicleSimulatorConfig()
        self.state_updater.config = config.updater or TrafficStateUpdaterConfig()
        self.dynamic_router.config = config.router or DynamicRouterConfig()

    def clear_route_congestion(self) -> None:
        """Clear runtime road closures after the user ends or completes navigation."""
        for incident in self.incident_generator.incidents:
            if incident.is_active:
                incident.is_active = False
                incident.end_time = min(float(incident.end_time), float(self.current_time))
        self.incident_generator.incidents = []
        self.state_updater.update(
            self.graph,
            self.vehicles,
            [],
            current_time=float(self.current_time),
            dt=0.0,
        )
        for _node, attrs in self.graph.nodes(data=True):
            attrs["traffic_node_congestion"] = 0.0
        self.metrics.metrics.number_of_congested_edges = 0

    def check_navigation_reroute(
        self,
        *,
        route_planner: RoutePlanner | None = None,
        force: bool = False,
    ) -> RerouteDecision | None:
        """Check the navigation vehicle against the current edge state."""
        if self.navigation_vehicle is None:
            return None
        decision = self.dynamic_router.maybe_reroute(
            self.graph,
            self.navigation_vehicle,
            current_time=self.current_time,
            route_planner=route_planner,
            force=force,
        )
        self.last_reroute_decision = decision
        if decision and decision.rerouted:
            self.previous_navigation_route = decision.old_route
            self._refresh_navigation_result_after_reroute()
        return decision

    def _split_vehicles(self, vehicles: list[Vehicle]) -> None:
        self.background_vehicles = [vehicle for vehicle in vehicles if vehicle.is_background_vehicle and not vehicle.arrived]
        nav = [vehicle for vehicle in vehicles if not vehicle.is_background_vehicle and not vehicle.arrived]
        self.navigation_vehicle = nav[0] if nav else self.navigation_vehicle

    def _refresh_navigation_result_after_reroute(self) -> None:
        if self.navigation_vehicle is None:
            return
        plan = self.dynamic_router.last_plan
        if plan is not None and isinstance(plan.raw_result, NavigationResult):
            self.navigation_result = plan.raw_result
        else:
            route = [int(node) for node in self.navigation_vehicle.route[self.navigation_vehicle.current_edge_index :]]
            if self.navigation_vehicle.current_edge is not None:
                edge = self.navigation_vehicle.current_edge
                route = [int(edge[0]), *route[1:]]
            self.navigation_result = self._result_from_route(route, backend="dynamic_shortest_path")
        self._record_routing_runtime(self.navigation_result)

    def step(self, *, dt: float | None = None, route_planner: RoutePlanner | None = None) -> SimulationStepResult:
        """Advance one timestep using the required update order."""
        step_dt = float(dt if dt is not None else self.config.dt)
        generated = self.flow_generator.generate(self.graph, current_time=self.current_time, dt=step_dt)
        self.background_vehicles.extend(generated)

        incident_edges_before = {
            edge
            for incident in self.incident_generator.active_incidents(self.current_time)
            for edge in incident.affected_edges
        }
        active_incidents = self.incident_generator.step(self.graph, current_time=self.current_time, dt=step_dt)

        moved = self.vehicle_simulator.move(
            self.graph,
            self.vehicles,
            current_time=self.current_time,
            dt=step_dt,
        )
        self._split_vehicles(moved)

        next_time = self.current_time + step_dt
        triggered_route_incidents = self._maybe_trigger_route_congestion(next_time)
        active_incidents = self.incident_generator.active_incidents(next_time)
        incident_edges_after = {edge for incident in active_incidents for edge in incident.affected_edges}
        has_new_incident_edges = bool(incident_edges_after - incident_edges_before)
        self.state_updater.update(
            self.graph,
            self.vehicles,
            active_incidents,
            current_time=next_time,
            dt=step_dt,
        )
        self.current_time = next_time

        decision = None
        if self.navigation_vehicle is not None and (triggered_route_incidents or has_new_incident_edges):
            decision = self.check_navigation_reroute(route_planner=route_planner)

        metric_edges = {
            edge
            for vehicle in self.vehicles
            for edge in ([vehicle.current_edge] if vehicle.current_edge is not None else [])
        } | incident_edges_before | incident_edges_after
        self.metrics.record_network(self.graph, candidate_edges=metric_edges)
        self.metrics.record_navigation_vehicle(self.navigation_vehicle)
        self.metrics.record_reroute(decision)

        return SimulationStepResult(
            current_time=float(self.current_time),
            generated_vehicle_count=len(generated),
            total_vehicle_count=len(self.vehicles),
            active_incidents=active_incidents,
            reroute_decision=decision,
            metrics=self.metrics.metrics.to_dict(),
        )

    def run_for(self, duration: float, *, route_planner: RoutePlanner | None = None) -> list[SimulationStepResult]:
        """Run several steps. This is still online; each step only sees current state."""
        results: list[SimulationStepResult] = []
        end_time = self.current_time + max(0.0, float(duration))
        while self.current_time < end_time:
            results.append(self.step(route_planner=route_planner))
        return results

    def current_snapshot(self) -> TrafficSnapshot:
        """Convert current edge attributes to the existing GUI TrafficSnapshot format."""
        edge_states: dict[tuple[int, int], TrafficEdgeState] = {}
        active_event_edges = {
            edge
            for incident in self.incident_generator.active_incidents(self.current_time)
            for edge in incident.affected_edges
        }
        vehicle_edges = {
            edge
            for vehicle in self.vehicles
            for edge in ([vehicle.current_edge] if vehicle.current_edge is not None else [])
        }
        snapshot_edges = {edge for edge in active_event_edges | vehicle_edges if self.graph.has_edge(*edge)}
        for u, v in snapshot_edges:
            attrs = self.graph[u][v]
            edge = (int(u), int(v))
            congestion = float(attrs.get("congestion_level", attrs.get("traffic_congestion", 0.0)) or 0.0)
            vehicle_count = int(attrs.get("vehicle_count", 0) or 0)
            if congestion <= 0.001 and vehicle_count <= 0 and edge not in active_event_edges:
                continue
            free_flow_time = float(attrs.get("free_flow_time", attrs.get("travel_time", 1.0)) or 1.0)
            travel_time = float(attrs.get("travel_time", free_flow_time) or free_flow_time)
            edge_states[edge] = TrafficEdgeState(
                edge=edge,
                vehicle_count=vehicle_count,
                congestion=congestion,
                delay_factor=max(1.0, travel_time / max(0.1, free_flow_time)),
                blocked=bool(attrs.get("state") == "blocked" or attrs.get("snn_synapse_closed")),
            )
        return TrafficSnapshot(
            step=int(round(self.current_time)),
            edge_states=edge_states,
            inhibited_nodes={
                int(v): float(self.graph.nodes[v].get("traffic_node_congestion", 0.0) or 0.0)
                for _u, v in active_event_edges
                if v in self.graph and self.graph.nodes[v].get("traffic_node_congestion")
            },
            metadata={
                "current_time": float(self.current_time),
                "vehicle_count": len(self.vehicles),
                "active_incidents": len(self.incident_generator.active_incidents(self.current_time)),
            },
        )

    def baseline_report(self, origin: int, destination: int) -> dict[str, dict[str, float | int | list[int] | None]]:
        project_route = self.navigation_result.path_nodes if self.navigation_result else None
        return compare_baselines(self.graph, int(origin), int(destination), project_route=project_route)
