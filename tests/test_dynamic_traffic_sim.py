"""Tests for runtime road-edge dynamic traffic simulation."""

from __future__ import annotations

import networkx as nx

from navigation import NavigationResult
from traffic import (
    DynamicRouter,
    DynamicRouterConfig,
    FlowGeneratorConfig,
    IncidentGenerator,
    IncidentGeneratorConfig,
    SimulationEngine,
    SimulationEngineConfig,
    TrafficIncident,
    initialize_edge_state,
)
from traffic.vehicle import make_navigation_vehicle


def _dynamic_graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    for node in range(4):
        graph.add_node(node, lat=0.0, lon=float(node) / 1000.0, x=float(node) / 1000.0, y=0.0, snn_neuron_index=node)
    graph.add_edge(0, 1, length=100.0, highway="primary")
    graph.add_edge(1, 3, length=100.0, highway="primary")
    graph.add_edge(1, 2, length=100.0, highway="primary")
    graph.add_edge(2, 3, length=100.0, highway="primary")
    graph.add_edge(3, 0, length=100.0, highway="primary")
    return initialize_edge_state(graph)


def test_initialize_edge_state_adds_required_dynamic_fields():
    graph = _dynamic_graph()
    attrs = graph[0][1]

    assert attrs["free_flow_speed"] > 0
    assert attrs["current_speed"] == attrs["free_flow_speed"]
    assert attrs["free_flow_time"] > 0
    assert attrs["travel_time"] > 0
    assert attrs["capacity"] > 0
    assert attrs["vehicle_count"] == 0
    assert attrs["density"] == 0.0
    assert attrs["flow"] == 0.0
    assert attrs["congestion_level"] == 0.0
    assert attrs["last_updated_time"] == 0.0


def test_incident_generator_activates_only_when_step_runs():
    graph = _dynamic_graph()
    generator = IncidentGenerator(
        IncidentGeneratorConfig(
            incident_probability_per_minute=1.0,
            incident_duration_min_seconds=120.0,
            incident_duration_max_seconds=120.0,
            random_seed=1,
        )
    )

    assert generator.active_incidents(0.0) == []
    active = generator.step(graph, current_time=0.0, dt=60.0)

    assert len(active) == 1
    assert active[0].start_time == 0.0
    assert active[0].is_active is True


def test_dynamic_router_reroutes_from_current_edge_end_using_current_travel_time():
    graph = _dynamic_graph()
    graph[1][3]["travel_time"] = 100.0
    graph[1][3]["congestion_level"] = 0.95
    graph[1][2]["travel_time"] = 5.0
    graph[2][3]["travel_time"] = 5.0
    vehicle = make_navigation_vehicle("nav", 0, 3, [0, 1, 3], 0.0)
    vehicle.last_reroute_time = -100.0
    vehicle.position_on_edge = 50.0
    router = DynamicRouter(
        DynamicRouterConfig(
            reroute_check_interval=0.0,
            min_reroute_interval=0.0,
            eta_improvement_threshold=0.15,
            congestion_threshold=0.8,
        )
    )

    decision = router.maybe_reroute(graph, vehicle, current_time=10.0)

    assert decision is not None
    assert decision.rerouted is True
    assert decision.old_route == [1, 3]
    assert decision.new_route == [1, 2, 3]
    assert vehicle.route == [0, 1, 2, 3]
    assert decision.affected_edge_ids == [(1, 3)]


def test_dynamic_router_blocks_immediate_backtrack_during_reroute():
    graph = nx.DiGraph()
    for node in range(4):
        graph.add_node(node, lat=0.0, lon=float(node), x=float(node), y=0.0, snn_neuron_index=node)
    graph.add_edge(0, 1, travel_time=1.0, length=1.0, state="normal")
    graph.add_edge(1, 0, travel_time=1.0, length=1.0, state="normal")
    graph.add_edge(0, 3, travel_time=1.0, length=1.0, state="normal")
    graph.add_edge(1, 3, travel_time=100.0, length=1.0, congestion_level=0.95, state="normal")
    graph.add_edge(1, 2, travel_time=5.0, length=1.0, state="normal")
    graph.add_edge(2, 3, travel_time=5.0, length=1.0, state="normal")
    vehicle = make_navigation_vehicle("nav", 0, 3, [0, 1, 3], 0.0)
    vehicle.last_reroute_time = -100.0
    vehicle.position_on_edge = 0.5
    router = DynamicRouter(
        DynamicRouterConfig(
            reroute_check_interval=0.0,
            min_reroute_interval=0.0,
            eta_improvement_threshold=0.15,
            congestion_threshold=0.8,
        )
    )

    decision = router.maybe_reroute(graph, vehicle, current_time=10.0)

    assert decision is not None
    assert decision.rerouted is True
    assert decision.new_route == [1, 2, 3]
    assert vehicle.route == [0, 1, 2, 3]


def test_simulation_engine_generates_runtime_vehicles_and_updates_metrics():
    graph = _dynamic_graph()
    engine = SimulationEngine(
        graph,
        SimulationEngineConfig(
            dt=5.0,
            random_seed=2,
            flow=FlowGeneratorConfig(
                traffic_mode="normal",
                base_rate_veh_per_minute=120.0,
                min_od_distance_m=0.0,
                random_seed=2,
            ),
            incidents=IncidentGeneratorConfig(incident_probability_per_minute=0.0, random_seed=3),
        ),
    )
    engine.start_navigation(0, 3)
    result = engine.step()

    assert result.generated_vehicle_count >= 1
    assert result.total_vehicle_count >= 1
    assert result.current_time == 5.0
    assert result.metrics["samples"] == 1
    assert "number_of_congested_edges" in result.metrics


def test_start_navigation_from_existing_result_does_not_replan():
    graph = _dynamic_graph()
    engine = SimulationEngine(
        graph,
        SimulationEngineConfig(
            flow=FlowGeneratorConfig(base_rate_veh_per_minute=0.0, random_seed=2),
            incidents=IncidentGeneratorConfig(incident_probability_per_minute=0.0, random_seed=3),
        ),
    )
    result = NavigationResult(
        start_node=0,
        goal_node=3,
        path_nodes=[0, 1, 3],
        path_edges=[(0, 1), (1, 3)],
        metadata={"success": True, "snn_runtime_sec": 1.25},
    )

    started = engine.start_navigation_from_result(result)

    assert started is result
    assert engine.navigation_vehicle is not None
    assert engine.navigation_vehicle.route == [0, 1, 3]
    assert engine.navigation_result is result


def test_simulation_step_does_not_call_route_planner_without_new_incident():
    graph = _dynamic_graph()
    engine = SimulationEngine(
        graph,
        SimulationEngineConfig(
            dt=1.0,
            flow=FlowGeneratorConfig(base_rate_veh_per_minute=0.0, random_seed=2),
            incidents=IncidentGeneratorConfig(incident_probability_per_minute=0.0, random_seed=3),
            route_congestion_interval_m=10_000.0,
        ),
    )
    engine.start_navigation(0, 3)
    calls = 0

    def route_planner(_graph, _source, _target):
        nonlocal calls
        calls += 1
        raise AssertionError("route planner should only run when a new incident appears")

    engine.step(route_planner=route_planner)

    assert calls == 0


def test_forced_resume_check_reroutes_using_current_state_despite_intervals():
    graph = _dynamic_graph()
    engine = SimulationEngine(
        graph,
        SimulationEngineConfig(
            router=DynamicRouterConfig(
                reroute_check_interval=999.0,
                min_reroute_interval=999.0,
                eta_improvement_threshold=0.15,
                congestion_threshold=0.8,
            ),
            incidents=IncidentGeneratorConfig(incident_probability_per_minute=0.0, random_seed=3),
            flow=FlowGeneratorConfig(base_rate_veh_per_minute=0.0, random_seed=2),
        ),
    )
    engine.start_navigation(0, 3)
    assert engine.navigation_vehicle is not None
    assert engine.navigation_vehicle.route == [0, 1, 3]
    engine.navigation_vehicle.position_on_edge = 50.0

    engine.graph[1][3]["travel_time"] = 100.0
    engine.graph[1][3]["congestion_level"] = 0.95
    engine.graph[1][2]["travel_time"] = 5.0
    engine.graph[2][3]["travel_time"] = 5.0

    assert engine.check_navigation_reroute(force=False) is None
    decision = engine.check_navigation_reroute(force=True)

    assert decision is not None
    assert decision.rerouted is True
    assert decision.old_route == [1, 3]
    assert decision.new_route == [1, 2, 3]
    assert engine.previous_navigation_route == [1, 3]
    assert engine.navigation_vehicle.route == [0, 1, 2, 3]


def test_distance_triggered_route_congestion_closes_snn_nodes_and_synapses():
    graph = nx.DiGraph()
    for node in range(4):
        graph.add_node(node, lat=0.0, lon=float(node) / 1000.0, x=float(node) / 1000.0, y=0.0, snn_neuron_index=node)
    graph.add_edge(0, 1, length=100.0, highway="primary")
    graph.add_edge(1, 2, length=100.0, highway="primary")
    graph.add_edge(2, 3, length=100.0, highway="primary")
    graph.add_edge(1, 3, length=500.0, highway="primary")
    graph = initialize_edge_state(graph)
    engine = SimulationEngine(
        graph,
        SimulationEngineConfig(
            dt=5.0,
            flow=FlowGeneratorConfig(base_rate_veh_per_minute=0.0, random_seed=2),
            incidents=IncidentGeneratorConfig(incident_probability_per_minute=0.0, random_seed=3),
            router=DynamicRouterConfig(reroute_check_interval=0.0, min_reroute_interval=0.0),
            route_congestion_interval_m=50.0,
            route_congestion_edge_count=1,
            route_congestion_duration_seconds=600.0,
        ),
    )
    engine.start_navigation(0, 3)

    result = engine.step()
    snapshot = engine.current_snapshot()

    assert result.active_incidents
    assert snapshot.blocked_edges
    blocked_edge = next(iter(snapshot.blocked_edges))
    assert engine.graph[blocked_edge[0]][blocked_edge[1]]["snn_synapse_closed"] is True
    assert engine.graph.nodes[blocked_edge[1]].get("snn_neuron_closed") is not True
    assert snapshot.inhibited_nodes[blocked_edge[1]] == 1.0


def test_route_congestion_does_not_close_cut_edge_without_detour():
    graph = nx.DiGraph()
    for node in range(4):
        graph.add_node(node, lat=0.0, lon=float(node) / 1000.0, x=float(node) / 1000.0, y=0.0, snn_neuron_index=node)
    graph.add_edge(0, 1, length=100.0, highway="primary")
    graph.add_edge(1, 2, length=100.0, highway="primary")
    graph.add_edge(2, 3, length=100.0, highway="primary")
    graph = initialize_edge_state(graph)
    engine = SimulationEngine(
        graph,
        SimulationEngineConfig(
            dt=5.0,
            flow=FlowGeneratorConfig(base_rate_veh_per_minute=0.0, random_seed=2),
            incidents=IncidentGeneratorConfig(incident_probability_per_minute=0.0, random_seed=3),
            router=DynamicRouterConfig(reroute_check_interval=0.0, min_reroute_interval=0.0),
            route_congestion_interval_m=50.0,
            route_congestion_edge_count=1,
            route_congestion_duration_seconds=600.0,
        ),
    )
    engine.start_navigation(0, 3)

    result = engine.step()

    assert result.active_incidents == []
    assert not engine.current_snapshot().blocked_edges


def test_expired_route_congestion_restores_edge_and_node_state():
    graph = nx.DiGraph()
    for node in range(4):
        graph.add_node(node, lat=0.0, lon=float(node) / 1000.0, x=float(node) / 1000.0, y=0.0, snn_neuron_index=node)
    graph.add_edge(0, 1, length=100.0, highway="primary")
    graph.add_edge(1, 2, length=100.0, highway="primary")
    graph.add_edge(2, 3, length=100.0, highway="primary")
    graph.add_edge(1, 3, length=300.0, highway="primary")
    graph = initialize_edge_state(graph)
    engine = SimulationEngine(
        graph,
        SimulationEngineConfig(
            dt=5.0,
            flow=FlowGeneratorConfig(base_rate_veh_per_minute=0.0, random_seed=2),
            incidents=IncidentGeneratorConfig(incident_probability_per_minute=0.0, random_seed=3),
            router=DynamicRouterConfig(reroute_check_interval=0.0, min_reroute_interval=0.0),
            route_congestion_interval_m=50.0,
            route_congestion_edge_count=1,
            route_congestion_duration_seconds=1.0,
        ),
    )
    engine.start_navigation(0, 3)

    engine.step()
    blocked_edges = list(engine.current_snapshot().blocked_edges)
    assert blocked_edges
    blocked_edge = blocked_edges[0]

    engine.step(dt=5.0)

    assert engine.graph[blocked_edge[0]][blocked_edge[1]]["state"] == "normal"
    assert engine.graph[blocked_edge[0]][blocked_edge[1]]["snn_synapse_closed"] is False
    assert engine.graph.nodes[blocked_edge[1]].get("snn_neuron_closed") is not True


def test_clear_route_congestion_resets_closed_edges_nodes_and_metric():
    graph = nx.DiGraph()
    for node in range(4):
        graph.add_node(node, lat=0.0, lon=float(node) / 1000.0, x=float(node) / 1000.0, y=0.0, snn_neuron_index=node)
    graph.add_edge(0, 1, length=100.0, highway="primary")
    graph.add_edge(1, 2, length=100.0, highway="primary")
    graph.add_edge(2, 3, length=100.0, highway="primary")
    graph.add_edge(1, 3, length=300.0, highway="primary")
    graph = initialize_edge_state(graph)
    engine = SimulationEngine(
        graph,
        SimulationEngineConfig(
            dt=5.0,
            flow=FlowGeneratorConfig(base_rate_veh_per_minute=0.0, random_seed=2),
            incidents=IncidentGeneratorConfig(incident_probability_per_minute=0.0, random_seed=3),
            router=DynamicRouterConfig(reroute_check_interval=0.0, min_reroute_interval=0.0),
            route_congestion_interval_m=50.0,
            route_congestion_edge_count=1,
            route_congestion_duration_seconds=600.0,
        ),
    )
    engine.start_navigation(0, 3)
    engine.step()
    blocked_edges = list(engine.current_snapshot().blocked_edges)
    assert blocked_edges
    blocked_edge = blocked_edges[0]
    engine.metrics.metrics.number_of_congested_edges = 1

    engine.clear_route_congestion()
    snapshot = engine.current_snapshot()

    assert engine.graph[blocked_edge[0]][blocked_edge[1]]["state"] == "normal"
    assert engine.graph[blocked_edge[0]][blocked_edge[1]]["snn_synapse_closed"] is False
    assert engine.graph.nodes[blocked_edge[1]].get("traffic_node_congestion", 0.0) == 0.0
    assert not snapshot.blocked_edges
    assert snapshot.inhibited_nodes == {}
    assert engine.metrics.metrics.number_of_congested_edges == 0


def test_blocked_edge_does_not_close_intersection_node_for_reroute():
    graph = nx.DiGraph()
    for node in range(4):
        graph.add_node(node, lat=0.0, lon=float(node) / 1000.0, x=float(node) / 1000.0, y=0.0)
    graph.add_edge(0, 1, length=100.0, highway="primary")
    graph.add_edge(1, 3, length=100.0, highway="primary")
    graph.add_edge(0, 2, length=120.0, highway="primary")
    graph.add_edge(2, 3, length=120.0, highway="primary")
    graph = initialize_edge_state(graph)
    engine = SimulationEngine(
        graph,
        SimulationEngineConfig(
            dt=1.0,
            flow=FlowGeneratorConfig(base_rate_veh_per_minute=0.0, random_seed=2),
            incidents=IncidentGeneratorConfig(incident_probability_per_minute=0.0, random_seed=3),
        ),
    )
    incident = TrafficIncident(
        event_id="test-closure",
        affected_edges=[(1, 3)],
        event_type="route_congestion",
        start_time=0.0,
        end_time=600.0,
        capacity_multiplier=0.01,
        speed_multiplier=0.01,
    )
    engine.incident_generator.incidents.append(incident)
    engine.state_updater.update(engine.graph, [], [incident], current_time=0.0, dt=1.0)

    route = nx.shortest_path(
        nx.subgraph_view(
            engine.graph,
            filter_edge=lambda u, v: engine.graph[u][v].get("state") != "blocked",
        ),
        0,
        3,
        weight="travel_time",
    )

    assert engine.graph[1][3]["state"] == "blocked"
    assert engine.graph.nodes[3].get("snn_neuron_closed") is not True
    assert route == [0, 2, 3]
