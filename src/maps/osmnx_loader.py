"""Load and cache real road networks from OpenStreetMap with OSMnx."""

from __future__ import annotations

import hashlib
import inspect
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import requests

_MPL_CACHE = Path(__file__).resolve().parents[2] / ".matplotlib-cache"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))
# A stale PROJ_LIB from another conda env can break pyproj/OSMnx imports.
os.environ.pop("PROJ_LIB", None)


@dataclass(frozen=True)
class BoundingBox:
    north: float
    south: float
    east: float
    west: float


def _import_osmnx():
    try:
        import osmnx as ox
    except Exception as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError(
            "OSMnx is required to download or load OSM road networks. "
            "Install dependencies with `pip install -r requirements.txt`."
        ) from exc
    return ox


def _safe_slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("_")
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"{text[:80] or 'map'}_{digest}"


def _bbox_slug(bbox: BoundingBox) -> str:
    raw = f"{bbox.north:.6f}_{bbox.south:.6f}_{bbox.east:.6f}_{bbox.west:.6f}"
    return _safe_slug(f"bbox_{raw}")


def _cache_path(
    *,
    cache_dir: str | Path,
    place_name: str | None,
    bbox: BoundingBox | None,
    network_type: str,
) -> Path:
    root = Path(cache_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    if place_name:
        slug = _safe_slug(f"{place_name}_{network_type}")
    elif bbox:
        slug = _safe_slug(f"{_bbox_slug(bbox)}_{network_type}")
    else:
        raise ValueError("place_name or bbox is required")
    return root / f"{slug}.graphml"


def _graph_from_bbox(ox: Any, bbox: BoundingBox, network_type: str) -> nx.MultiDiGraph:
    signature = inspect.signature(ox.graph_from_bbox)
    if "bbox" in signature.parameters:
        try:
            return ox.graph_from_bbox(
                bbox=(bbox.west, bbox.south, bbox.east, bbox.north),
                network_type=network_type,
            )
        except TypeError:
            return ox.graph_from_bbox(
                bbox=(bbox.north, bbox.south, bbox.east, bbox.west),
                network_type=network_type,
            )
    return ox.graph_from_bbox(
        north=bbox.north,
        south=bbox.south,
        east=bbox.east,
        west=bbox.west,
        network_type=network_type,
    )


def _add_speed_and_travel_time(ox: Any, graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    try:
        graph = ox.add_edge_speeds(graph)
        graph = ox.add_edge_travel_times(graph)
    except Exception:
        for _u, _v, _key, attrs in graph.edges(keys=True, data=True):
            attrs.setdefault("travel_time", attrs.get("length", 1.0))
    return graph


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return float(2 * radius_m * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _parse_speed_mps(value: Any, fallback_mps: float = 13.9) -> float:
    if isinstance(value, list) and value:
        value = value[0]
    if value is None:
        return fallback_mps
    text = str(value).lower()
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return fallback_mps
    speed = float(match.group(1))
    if "mph" in text:
        return max(0.1, speed * 0.44704)
    return max(0.1, speed / 3.6)


def _place_to_bbox(place_name: str) -> BoundingBox:
    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": place_name, "format": "json", "limit": 1},
        headers={"User-Agent": "neuromorphic-osm-snn-navigation/0.1"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload:
        raise RuntimeError(f"place not found by Nominatim: {place_name}")
    south, north, west, east = [float(value) for value in payload[0]["boundingbox"]]
    return BoundingBox(north=north, south=south, east=east, west=west)


def _is_drive_way(tags: dict[str, Any], network_type: str) -> bool:
    highway = str(tags.get("highway", ""))
    if not highway:
        return False
    if network_type != "drive":
        return True
    excluded = {
        "bridleway",
        "corridor",
        "cycleway",
        "elevator",
        "escalator",
        "footway",
        "path",
        "pedestrian",
        "platform",
        "steps",
    }
    return highway not in excluded and str(tags.get("access", "")).lower() not in {"no", "private"}


def _manual_overpass_graph(
    *,
    place_name: str | None,
    bbox: BoundingBox | None,
    network_type: str,
) -> nx.MultiDiGraph:
    """Fallback OSM loader that does not depend on Shapely/GeoPandas."""
    if bbox is None:
        if not place_name:
            raise ValueError("place_name or bbox is required")
        bbox = _place_to_bbox(place_name)

    query = f"""
    [out:json][timeout:60];
    (
      way["highway"]({bbox.south},{bbox.west},{bbox.north},{bbox.east});
    );
    (._;>;);
    out body;
    """
    response = requests.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": query},
        headers={"User-Agent": "neuromorphic-osm-snn-navigation/0.1"},
        timeout=90,
    )
    response.raise_for_status()
    elements = response.json().get("elements", [])
    node_lookup: dict[int, dict[str, float]] = {}
    ways: list[dict[str, Any]] = []
    for element in elements:
        if element.get("type") == "node":
            node_lookup[int(element["id"])] = {"x": float(element["lon"]), "y": float(element["lat"])}
        elif element.get("type") == "way":
            ways.append(element)

    graph = nx.MultiDiGraph()
    for node_id, attrs in node_lookup.items():
        graph.add_node(node_id, **attrs)

    for way in ways:
        tags = dict(way.get("tags") or {})
        if not _is_drive_way(tags, network_type):
            continue
        nodes = [int(node) for node in way.get("nodes", []) if int(node) in node_lookup]
        if len(nodes) < 2:
            continue
        speed_mps = _parse_speed_mps(tags.get("maxspeed"))
        oneway = str(tags.get("oneway", "")).lower() in {"yes", "true", "1"}
        for u, v in zip(nodes, nodes[1:]):
            u_attrs = node_lookup[u]
            v_attrs = node_lookup[v]
            length = _haversine_m(u_attrs["y"], u_attrs["x"], v_attrs["y"], v_attrs["x"])
            travel_time = length / speed_mps
            edge_attrs = {
                "osmid": way.get("id"),
                "highway": tags.get("highway"),
                "length": float(length),
                "travel_time": float(travel_time),
                "oneway": oneway,
            }
            graph.add_edge(u, v, **edge_attrs)
            if not oneway:
                graph.add_edge(v, u, **edge_attrs)

    if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
        raise RuntimeError("Overpass returned no usable road edges; try a larger bbox.")
    graph.graph.update({"loader": "manual_overpass_fallback", "network_type": network_type})
    return graph


def _load_graphml(path: Path, ox: Any | None) -> nx.MultiDiGraph:
    if ox is not None:
        try:
            return ox.load_graphml(path)
        except Exception:
            pass
    return nx.read_graphml(path)


def _save_graphml(graph: nx.MultiDiGraph, path: Path, ox: Any | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if ox is not None and graph.graph.get("loader") != "manual_overpass_fallback":
        ox.save_graphml(graph, path)
    else:
        nx.write_graphml(graph, path)


def load_osm_graph(
    *,
    place_name: str | None = None,
    bbox: BoundingBox | None = None,
    network_type: str = "drive",
    cache_dir: str | Path = "data/osm_cache",
    use_cache: bool = True,
) -> nx.MultiDiGraph:
    """Load a real road network from cache or OpenStreetMap.

    Exactly one of `place_name` or `bbox` should be provided. Downloaded maps
    are cached as GraphML and reused on later runs.
    """
    if bool(place_name) == bool(bbox):
        raise ValueError("provide exactly one of place_name or bbox")

    try:
        ox = _import_osmnx()
    except RuntimeError:
        ox = None
    path = _cache_path(
        cache_dir=cache_dir,
        place_name=place_name,
        bbox=bbox,
        network_type=network_type,
    )
    if use_cache and path.exists():
        return _load_graphml(path, ox)

    graph: nx.MultiDiGraph
    try:
        if ox is not None:
            try:
                if place_name:
                    graph = ox.graph_from_place(place_name, network_type=network_type)
                else:
                    graph = _graph_from_bbox(ox, bbox, network_type)
                graph = _add_speed_and_travel_time(ox, graph)
            except Exception:
                graph = _manual_overpass_graph(place_name=place_name, bbox=bbox, network_type=network_type)
        else:
            graph = _manual_overpass_graph(place_name=place_name, bbox=bbox, network_type=network_type)
    except Exception as exc:
        raise RuntimeError(
            "Failed to load an OpenStreetMap road network. "
            "Check network access, try a smaller bbox/place, or reuse an existing GraphML cache in data/osm_cache."
        ) from exc

    if use_cache:
        _save_graphml(graph, path, ox)
    return graph
