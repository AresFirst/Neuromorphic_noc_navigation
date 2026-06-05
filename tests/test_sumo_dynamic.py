"""Dynamic SUMO traffic and wavefront visualization tests."""

from __future__ import annotations

from pathlib import Path

from nmn.sumo import (
    SumoTrafficVehicle,
    apply_traffic_congestion,
    draw_sumo_dynamic_frame,
    load_sumo_network_geometry,
    most_to_digraph,
    spawn_random_traffic_vehicles,
    traffic_vehicle_positions,
)


MOCK_SUMO_NET = """<net>
    <junction id="A" x="0.0" y="0.0" type="priority"/>
    <junction id="B" x="10.0" y="0.0" type="priority"/>
    <junction id="C" x="20.0" y="0.0" type="priority"/>
    <edge id="AB" from="A" to="B">
        <lane id="AB_0" index="0" speed="10.0" length="10.0" shape="0.0,0.0 10.0,0.0"/>
    </edge>
    <edge id="BC" from="B" to="C">
        <lane id="BC_0" index="0" speed="10.0" length="10.0" shape="10.0,0.0 20.0,0.0"/>
    </edge>
    <edge id="CA" from="C" to="A">
        <lane id="CA_0" index="0" speed="10.0" length="20.0" shape="20.0,0.0 0.0,0.0"/>
    </edge>
</net>
"""


def _write_net(tmp_path: Path) -> Path:
    path = tmp_path / "mock.net.xml"
    path.write_text(MOCK_SUMO_NET, encoding="utf-8")
    return path


def test_spawn_random_traffic_vehicles_uses_graph_edges(tmp_path):
    graph, _geometry = most_to_digraph(_write_net(tmp_path), max_nodes=None, seed=0)

    vehicles = spawn_random_traffic_vehicles(graph, num_vehicles=5, seed=0)

    assert len(vehicles) == 5
    assert all(graph.has_edge(*vehicle.edge) for vehicle in vehicles)
    assert all(0.0 <= vehicle.progress < 1.0 for vehicle in vehicles)


def test_apply_traffic_congestion_maps_density_to_delay_and_blocked_state(tmp_path):
    graph, _geometry = most_to_digraph(_write_net(tmp_path), max_nodes=None, seed=0)
    node_map = graph.graph["sumo_node_id_to_node_id"]
    source = node_map["A"]
    target = node_map["B"]
    original_delay = graph[source][target]["delay_ms"]
    vehicles = [
        SumoTrafficVehicle("veh_0", source, target, progress=0.2, speed=0.1),
        SumoTrafficVehicle("veh_1", source, target, progress=0.6, speed=0.1),
    ]

    state = apply_traffic_congestion(
        graph,
        vehicles,
        congested_density=0.5,
        blocked_density=3.0,
        delay_factor=2.0,
        vehicles_per_lane_capacity=2.0,
        threshold_penalty_ms=2.0,
    )

    assert (source, target) in state["congested_edges"]
    assert graph[source][target]["state"] == "congested"
    assert graph[source][target]["delay_ms"] > original_delay
    assert graph.nodes[target]["threshold_penalty"] > 0

    state = apply_traffic_congestion(
        graph,
        vehicles,
        congested_density=0.5,
        blocked_density=0.75,
        delay_factor=2.0,
        vehicles_per_lane_capacity=2.0,
        threshold_penalty_ms=2.0,
    )

    assert (source, target) in state["blocked_edges"]
    assert graph[source][target]["state"] == "blocked"


def test_traffic_vehicle_positions_interpolates_along_sumo_shape(tmp_path):
    graph, _geometry = most_to_digraph(_write_net(tmp_path), max_nodes=None, seed=0)
    node_map = graph.graph["sumo_node_id_to_node_id"]
    vehicle = SumoTrafficVehicle("veh_0", node_map["A"], node_map["B"], progress=0.5, speed=0.1)

    positions = traffic_vehicle_positions(graph, [vehicle])

    assert positions[0]["x"] == 5.0
    assert positions[0]["y"] == 0.0
    assert positions[0]["sumo_edge_id"] == "AB"


def test_draw_sumo_dynamic_frame_outputs_png(tmp_path):
    netxml = _write_net(tmp_path)
    graph, geometry = most_to_digraph(netxml, max_nodes=None, seed=0)
    node_map = graph.graph["sumo_node_id_to_node_id"]
    path = [node_map["A"], node_map["B"], node_map["C"]]
    route_segments = [
        {
            "sumo_edge_id": "AB",
            "shape": [[0.0, 0.0], [10.0, 0.0]],
        },
        {
            "sumo_edge_id": "BC",
            "shape": [[10.0, 0.0], [20.0, 0.0]],
        },
    ]
    vehicles = [SumoTrafficVehicle("veh_0", path[0], path[1], progress=0.5, speed=0.1)]
    output = tmp_path / "dynamic.png"

    draw_sumo_dynamic_frame(
        load_sumo_network_geometry(netxml),
        graph,
        save_path=str(output),
        route_segments=route_segments,
        wavefront_result={"spike_times_by_neuron": {path[0]: 0.0, path[1]: 1.0, path[2]: 2.0}},
        wavefront_time_ms=2.0,
        vehicle_positions=traffic_vehicle_positions(graph, vehicles),
        congested_edges=[(path[0], path[1])],
        blocked_edges=[],
        current_node=path[0],
        target_node=path[2],
    )

    assert geometry.edges["AB"].shape
    assert output.exists()
    assert output.stat().st_size > 1000
