"""Tests for fixed Hangzhou OSM cache behavior."""

from __future__ import annotations

import networkx as nx
import pytest

from maps import HANGZHOU_BBOX, HANGZHOU_CACHE_FILENAME_TEMPLATE, load_hangzhou_graph
import maps.osmnx_loader as loader


def _raise_missing_osmnx():
    raise RuntimeError("osmnx unavailable in test")


def test_load_hangzhou_graph_prefers_stable_local_cache(tmp_path, monkeypatch):
    cache_file = tmp_path / HANGZHOU_CACHE_FILENAME_TEMPLATE.format(network_type="drive")
    cache_file.write_text("<graphml />", encoding="utf-8")
    cached_graph = nx.MultiDiGraph()
    called: dict[str, object] = {}

    def fake_load_graphml(path, ox):
        called["path"] = path
        called["ox"] = ox
        return cached_graph

    def unexpected_download(**_kwargs):
        pytest.fail("cache hit should not call OSM download fallback")

    monkeypatch.setattr(loader, "_import_osmnx", _raise_missing_osmnx)
    monkeypatch.setattr(loader, "_load_graphml", fake_load_graphml)
    monkeypatch.setattr(loader, "_manual_overpass_graph", unexpected_download)

    graph = load_hangzhou_graph(cache_dir=tmp_path)

    assert graph is cached_graph
    assert called["path"] == cache_file
    assert called["ox"] is None


def test_load_hangzhou_graph_crops_stale_fixed_cache(tmp_path, monkeypatch):
    fixed_cache = tmp_path / HANGZHOU_CACHE_FILENAME_TEMPLATE.format(network_type="drive")
    fixed_cache.write_text("<graphml />", encoding="utf-8")
    stale_graph = nx.MultiDiGraph()
    stale_graph.add_node(1, x=120.10, y=30.30)
    stale_graph.add_node(2, x=120.11, y=30.31)
    stale_graph.add_node(3, x=119.00, y=31.00)
    stale_graph.add_edge(1, 2, length=10.0, travel_time=1.0)
    stale_graph.add_edge(2, 3, length=10.0, travel_time=1.0)
    called: dict[str, object] = {}

    def fake_load_graphml(path, ox):
        called["loaded_path"] = path
        return stale_graph

    def fake_save(graph, path, ox):
        called["saved_graph"] = graph
        called["saved_path"] = path

    def unexpected_download(**_kwargs):
        pytest.fail("stale fixed cache should be cropped before any OSM download fallback")

    monkeypatch.setattr(loader, "_import_osmnx", _raise_missing_osmnx)
    monkeypatch.setattr(loader, "_load_graphml", fake_load_graphml)
    monkeypatch.setattr(loader, "_save_graphml", fake_save)
    monkeypatch.setattr(loader, "_manual_overpass_graph", unexpected_download)

    graph = load_hangzhou_graph(cache_dir=tmp_path)

    assert graph.number_of_nodes() == 2
    assert graph.number_of_edges() == 1
    assert called["loaded_path"] == fixed_cache
    assert called["saved_path"] == fixed_cache
    assert called["saved_graph"] is graph


def test_load_hangzhou_graph_downloads_to_stable_cache_when_missing(tmp_path, monkeypatch):
    downloaded_graph = nx.MultiDiGraph()
    downloaded_graph.add_node(1, x=120.0, y=30.2)
    downloaded_graph.add_node(2, x=120.1, y=30.3)
    downloaded_graph.add_edge(1, 2, length=10.0, travel_time=1.0)
    called: dict[str, object] = {}

    def fake_download(*, place_name, bbox, network_type):
        called["place_name"] = place_name
        called["bbox"] = bbox
        called["network_type"] = network_type
        return downloaded_graph

    def fake_save(graph, path, ox):
        called["saved_graph"] = graph
        called["saved_path"] = path
        called["saved_ox"] = ox

    monkeypatch.setattr(loader, "_import_osmnx", _raise_missing_osmnx)
    monkeypatch.setattr(loader, "_manual_overpass_graph", fake_download)
    monkeypatch.setattr(loader, "_save_graphml", fake_save)

    graph = load_hangzhou_graph(cache_dir=tmp_path)

    assert graph is downloaded_graph
    assert called["place_name"] is None
    assert called["bbox"] == HANGZHOU_BBOX
    assert called["network_type"] == "drive"
    assert called["saved_graph"] is downloaded_graph
    assert called["saved_path"] == tmp_path / HANGZHOU_CACHE_FILENAME_TEMPLATE.format(network_type="drive")
    assert called["saved_ox"] is None


def test_load_hangzhou_graph_can_crop_legacy_cache(tmp_path, monkeypatch):
    fixed_cache = tmp_path / HANGZHOU_CACHE_FILENAME_TEMPLATE.format(network_type="drive")
    legacy_cache = tmp_path / "hangzhou_drive.graphml"
    legacy_cache.write_text("<graphml />", encoding="utf-8")
    legacy_graph = nx.MultiDiGraph()
    legacy_graph.add_node(1, x=120.10, y=30.30)
    legacy_graph.add_node(2, x=120.11, y=30.31)
    legacy_graph.add_node(3, x=121.00, y=31.00)
    legacy_graph.add_edge(1, 2, length=10.0, travel_time=1.0)
    legacy_graph.add_edge(2, 3, length=10.0, travel_time=1.0)
    legacy_graph.graph["simplified"] = False
    called: dict[str, object] = {}

    def fake_load_graphml(path, ox):
        called["loaded_path"] = path
        return legacy_graph

    def fake_save(graph, path, ox):
        called["saved_graph"] = graph
        called["saved_path"] = path

    def unexpected_download(**_kwargs):
        pytest.fail("legacy cache crop should not call OSM download fallback")

    monkeypatch.setattr(loader, "_import_osmnx", _raise_missing_osmnx)
    monkeypatch.setattr(loader, "_load_graphml", fake_load_graphml)
    monkeypatch.setattr(loader, "_save_graphml", fake_save)
    monkeypatch.setattr(loader, "_manual_overpass_graph", unexpected_download)

    graph = load_hangzhou_graph(cache_dir=tmp_path)

    assert graph.number_of_nodes() == 2
    assert graph.number_of_edges() == 1
    assert called["loaded_path"] == legacy_cache
    assert called["saved_path"] == fixed_cache
    assert called["saved_graph"] is graph
