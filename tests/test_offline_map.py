"""Tests for the offline map renderer payload and runtime detection."""

from __future__ import annotations

import networkx as nx

import gui.offline_map as offline_map
from gui.offline_map import (
    CANVAS_FALLBACK_RENDERER_NAME,
    LOCAL_OSM_RASTER_RENDERER_NAME,
    MAP_RENDERER_NAME,
    OSM_RASTER_RENDERER_NAME,
    build_offline_map_payload,
    get_offline_map_runtime,
)
from navigation import NavigationResult, WavefrontFrame


def _tiny_graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_node(0, lat=30.20, lon=120.10, x=120.10, y=30.20, snn_neuron_index=0)
    graph.add_node(1, lat=30.21, lon=120.11, x=120.11, y=30.21, snn_neuron_index=1)
    graph.add_node(2, lat=30.22, lon=120.12, x=120.12, y=30.22, snn_neuron_index=2)
    graph.add_edge(0, 1, length=10.0, travel_time=1.0)
    graph.add_edge(1, 2, length=10.0, travel_time=1.0)
    return graph


def test_offline_map_payload_uses_lonlat_geojson_and_markers():
    graph = _tiny_graph()
    edge_points = [
        (0, 1, [(30.20, 120.10), (30.21, 120.11)]),
        (1, 2, [(30.21, 120.11), (30.22, 120.12)]),
    ]
    result = NavigationResult(
        start_node=0,
        goal_node=2,
        path_nodes=[0, 1, 2],
        path_edges=[(0, 1), (1, 2)],
        wavefront_frames=[],
        total_cost=2.0,
        metadata={"success": True},
    )

    payload = build_offline_map_payload(
        graph,
        edge_points,
        {(u, v): points for u, v, points in edge_points},
        result=result,
        start_node=0,
        goal_node=2,
        car_point=(30.205, 120.105),
        traffic_snapshot=None,
        previous_route=[],
        wavefront_frame=WavefrontFrame(t=0, active_nodes=[0, 1], active_edges=[(0, 1)]),
        inflight_edges=[(1, 2)],
        draw_base_roads=True,
        max_base_edges=1,
        max_traffic_edges=10,
        max_wavefront_nodes=10,
    )

    assert payload["baseRoads"]["features"][0]["geometry"]["coordinates"][0] == [120.10, 30.20]
    assert len(payload["baseRoads"]["features"]) == 1
    assert payload["path"]["features"][0]["properties"]["color"] == "#dc2626"
    assert len(payload["markers"]["features"]) == 3
    assert payload["markers"]["features"][2]["properties"]["kind"] == "car"
    assert payload["wavefrontEdges"]["features"]
    assert payload["wavefrontInflight"]["features"]


def test_offline_runtime_uses_osm_raster_by_default_without_local_assets(tmp_path):
    runtime = get_offline_map_runtime(
        asset_dir=tmp_path / "assets",
        mbtiles_path=tmp_path / "hangzhou.mbtiles",
        pmtiles_path=tmp_path / "hangzhou.pmtiles",
        raster_tile_dir=tmp_path / "osm",
    )

    assert runtime.renderer == OSM_RASTER_RENDERER_NAME
    assert runtime.uses_leaflet_raster is True
    assert runtime.raster_tile_url == "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    assert runtime.uses_maplibre is False
    assert "OpenStreetMap 标准底图" in runtime.messages[0]


def test_offline_runtime_can_force_canvas_without_online_osm(tmp_path):
    runtime = get_offline_map_runtime(
        asset_dir=tmp_path / "assets",
        mbtiles_path=tmp_path / "hangzhou.mbtiles",
        pmtiles_path=tmp_path / "hangzhou.pmtiles",
        raster_tile_dir=tmp_path / "osm",
        allow_online_osm=False,
    )

    assert runtime.renderer == CANVAS_FALLBACK_RENDERER_NAME
    assert runtime.uses_maplibre is False
    assert runtime.uses_leaflet_raster is False
    assert runtime.server_url is None
    assert "Canvas 离线降级渲染" in runtime.messages[0]


def test_offline_runtime_detects_local_osm_raster_tiles(tmp_path, monkeypatch):
    raster_dir = tmp_path / "osm"
    tile_dir = raster_dir / "12" / "3415"
    tile_dir.mkdir(parents=True)
    (tile_dir / "1680.png").write_bytes(b"png")
    monkeypatch.setattr(offline_map, "_ensure_server", lambda *_args, **_kwargs: "http://127.0.0.1:12345")

    runtime = get_offline_map_runtime(
        asset_dir=tmp_path / "assets",
        mbtiles_path=tmp_path / "hangzhou.mbtiles",
        pmtiles_path=tmp_path / "hangzhou.pmtiles",
        raster_tile_dir=raster_dir,
    )

    assert runtime.renderer == LOCAL_OSM_RASTER_RENDERER_NAME
    assert runtime.uses_leaflet_raster is True
    assert runtime.raster_tile_url == "http://127.0.0.1:12345/osm/{z}/{x}/{y}.png"
    assert runtime.server_url == "http://127.0.0.1:12345"
    assert "本地 OpenStreetMap 栅格瓦片" in runtime.messages[0]


def test_offline_runtime_detects_maplibre_geojson_mode_without_tiles(tmp_path, monkeypatch):
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    (asset_dir / "maplibre-gl.js").write_text("// test", encoding="utf-8")
    (asset_dir / "maplibre-gl.css").write_text("/* test */", encoding="utf-8")
    monkeypatch.setattr(offline_map, "_ensure_server", lambda *_args, **_kwargs: "http://127.0.0.1:12345")

    runtime = get_offline_map_runtime(
        asset_dir=asset_dir,
        mbtiles_path=tmp_path / "hangzhou.mbtiles",
        pmtiles_path=tmp_path / "hangzhou.pmtiles",
        raster_tile_dir=tmp_path / "osm",
        allow_online_osm=False,
    )

    assert runtime.uses_maplibre is True
    assert runtime.uses_leaflet_raster is False
    assert runtime.renderer == "MapLibre 本地 GeoJSON 渲染"
    assert runtime.maplibre_js_url is not None
    assert runtime.maplibre_css_url is not None
    assert runtime.tilejson_url is None
    assert runtime.pmtiles_url is None
    assert MAP_RENDERER_NAME == "MapLibre 本地矢量瓦片"
