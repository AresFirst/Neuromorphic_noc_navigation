"""Tests for PySide6 desktop viewer pure helpers."""

from __future__ import annotations

import networkx as nx

from gui.desktop_viewer import (
    DEFAULT_TILE_ZOOM,
    build_scene_node_positions,
    coordinate_in_hangzhou,
    latlon_to_tile_pixel,
    nearest_scene_node,
    node_mapping_text,
    point_along_polyline,
    polyline_length_m,
    tile_pixel_to_latlon,
    tile_range_for_bounds,
)


def _graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_node(0, lat=30.20, lon=120.10, x=120.10, y=30.20, original_osm_node_id=123, snn_neuron_index=0)
    graph.add_node(1, lat=30.21, lon=120.11, x=120.11, y=30.21, original_osm_node_id=456, snn_neuron_index=1)
    graph.add_edge(0, 1, length=100.0, travel_time=10.0)
    return graph


def test_web_mercator_projection_roundtrips_hangzhou_coordinate():
    lat, lon = 30.25, 120.16

    x, y = latlon_to_tile_pixel(lat, lon, zoom=DEFAULT_TILE_ZOOM)
    roundtrip_lat, roundtrip_lon = tile_pixel_to_latlon(x, y, zoom=DEFAULT_TILE_ZOOM)

    assert abs(roundtrip_lat - lat) < 1e-9
    assert abs(roundtrip_lon - lon) < 1e-9


def test_tile_range_for_bounds_is_non_empty_and_ordered():
    x_range, y_range = tile_range_for_bounds(30.42, 30.08, 120.36, 119.95, zoom=DEFAULT_TILE_ZOOM)

    assert len(x_range) > 0
    assert len(y_range) > 0
    assert x_range.start <= x_range.stop - 1
    assert y_range.start <= y_range.stop - 1


def test_node_scene_lookup_and_mapping_text_use_digraph_and_snn_ids():
    graph = _graph()
    positions = build_scene_node_positions(graph)
    x, y = positions[0]

    selected = nearest_scene_node(positions, x + 1.0, y + 1.0, max_distance_px=8.0)
    text = node_mapping_text(graph, 0)

    assert selected == 0
    assert "DiGraph 节点：0" in text
    assert "SNN neuron index：0" in text
    assert "OSM node id：123" in text


def test_vehicle_interpolation_along_polyline_reaches_end():
    points = [(30.20, 120.10), (30.20, 120.11)]
    length = polyline_length_m(points)

    start = point_along_polyline(points, 0.0)
    middle = point_along_polyline(points, length / 2.0)
    end = point_along_polyline(points, length * 2.0)

    assert start == points[0]
    assert middle is not None
    assert 120.10 < middle[1] < 120.11
    assert end == points[-1]


def test_desktop_coordinate_validation_uses_hangzhou_bbox():
    assert coordinate_in_hangzhou(30.25, 120.16)
    assert not coordinate_in_hangzhou(31.25, 120.16)
