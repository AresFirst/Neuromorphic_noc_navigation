"""Geometry-preserving SUMO conversion and overlay tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from nmn.sumo import (
    draw_sumo_route_overlay,
    load_sumo_network_geometry,
    most_to_digraph,
    parse_shape_points,
    path_to_sumo_route,
)


MOCK_SUMO_NET = """<net>
    <junction id="A" x="0.0" y="0.0" type="priority"/>
    <junction id="B" x="10.0" y="0.0" type="priority"/>
    <junction id="C" x="10.0" y="10.0" type="priority"/>
    <edge id="AB" from="A" to="B">
        <lane id="AB_0" index="0" speed="10.0" length="10.0" shape="0.0,0.0 5.0,1.0 10.0,0.0"/>
    </edge>
    <edge id="BC" from="B" to="C">
        <lane id="BC_0" index="0" speed="5.0" length="10.0" shape="10.0,0.0,0.0 10.0,5.0,0.0 10.0,10.0,0.0"/>
    </edge>
    <edge id="CA" from="C" to="A">
        <lane id="CA_0" index="0" speed="10.0" length="14.0" shape="10.0,10.0 5.0,5.0 0.0,0.0"/>
    </edge>
    <edge id=":A_0" function="internal" from="A" to="A">
        <lane id=":A_0_0" index="0" speed="1.0" length="1.0" shape="0.0,0.0 1.0,1.0"/>
    </edge>
</net>
"""


def _write_net(tmp_path: Path) -> Path:
    path = tmp_path / "mock.net.xml"
    path.write_text(MOCK_SUMO_NET, encoding="utf-8")
    return path


def test_parse_shape_points_accepts_2d_and_3d_tokens():
    assert parse_shape_points("1,2 3.5,4.5,0") == ((1.0, 2.0), (3.5, 4.5))


def test_load_sumo_network_geometry_preserves_lane_shapes(tmp_path):
    netxml = _write_net(tmp_path)
    geometry = load_sumo_network_geometry(netxml)

    assert set(geometry.nodes) == {"A", "B", "C"}
    assert set(geometry.edges) == {"AB", "BC", "CA"}
    assert geometry.edges["AB"].shape == ((0.0, 0.0), (5.0, 1.0), (10.0, 0.0))
    assert geometry.edges["BC"].shape == ((10.0, 0.0), (10.0, 5.0), (10.0, 10.0))


def test_most_to_digraph_keeps_reversible_sumo_mapping(tmp_path):
    netxml = _write_net(tmp_path)
    graph, geometry = most_to_digraph(netxml, max_nodes=None, seed=0)

    assert graph.graph["geometry_preserved"] is True
    assert graph.graph["visualization_source"] == "sumo_netxml"
    assert geometry.edges["AB"].shape

    node_map = graph.graph["sumo_node_id_to_node_id"]
    path = [node_map["A"], node_map["B"], node_map["C"]]
    route = path_to_sumo_route(graph, path)

    assert route["sumo_node_ids"] == ["A", "B", "C"]
    assert route["sumo_edge_ids"] == ["AB", "BC"]
    assert route["segments"][0]["shape"] == [[0.0, 0.0], [5.0, 1.0], [10.0, 0.0]]
    assert route["segments"][0]["lane_ids"] == ["AB_0"]


def test_path_to_sumo_route_rejects_missing_segments(tmp_path):
    netxml = _write_net(tmp_path)
    graph, _geometry = most_to_digraph(netxml, max_nodes=None, seed=0)
    node_map = graph.graph["sumo_node_id_to_node_id"]

    with pytest.raises(ValueError, match="missing graph edge"):
        path_to_sumo_route(graph, [node_map["A"], node_map["C"]])


def test_draw_sumo_route_overlay_uses_sumo_geometry(tmp_path):
    netxml = _write_net(tmp_path)
    graph, geometry = most_to_digraph(netxml, max_nodes=None, seed=0)
    node_map = graph.graph["sumo_node_id_to_node_id"]
    route = path_to_sumo_route(graph, [node_map["A"], node_map["B"], node_map["C"]])
    output = tmp_path / "overlay.png"

    draw_sumo_route_overlay(
        geometry,
        route_edge_ids=route["sumo_edge_ids"],
        route_segments=route["segments"],
        save_path=str(output),
    )

    assert output.exists()
    assert output.stat().st_size > 1000
