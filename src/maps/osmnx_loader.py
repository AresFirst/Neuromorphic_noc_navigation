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
# OSMnx/GeoPandas 在导入时可能触发 matplotlib 配置读取；固定到项目目录避免写入用户目录失败。
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))
# A stale PROJ_LIB from another conda env can break pyproj/OSMnx imports.
os.environ.pop("PROJ_LIB", None)


@dataclass(frozen=True)
class BoundingBox:
    # OSM/OSMnx 常用 north/south/east/west 描述经纬度矩形范围。
    # north/south 是纬度上/下边界，east/west 是经度右/左边界。
    north: float
    south: float
    east: float
    west: float


# Web GUI 固定使用杭州西湖/拱墅/余杭/上城附近区域。bbox 约为旧杭州固定
# bbox 的 1/4 面积，降低首次下载、SNN 规划和 Folium 渲染压力。
HANGZHOU_PLACE_NAME = "Hangzhou, Zhejiang, China"
HANGZHOU_BBOX = BoundingBox(north=30.390000, south=30.220000, east=120.235000, west=120.030000)
DEFAULT_FIXED_MAP_REGION = "杭州市西湖区 / 拱墅区 / 余杭区 / 上城区附近"
HANGZHOU_CACHE_FILENAME_TEMPLATE = "hangzhou_core_bidirectional_{network_type}.graphml"


def _import_osmnx():
    # OSMnx 是可选的大依赖；运行测试或离线 fallback 时不希望模块导入阶段直接失败。
    try:
        import osmnx as ox
    except Exception as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError(
            "OSMnx is required to download or load OSM road networks. "
            "Install dependencies with `pip install -r requirements.txt`."
        ) from exc
    return ox


def _safe_slug(value: str) -> str:
    # GraphML 缓存文件名需要同时可读和稳定；hash 防止长地名或相近 bbox 产生冲突。
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
    # 同一个 place/bbox 与 network_type 对应一个缓存文件；后续加载优先复用本地 GraphML。
    root = Path(cache_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    if place_name:
        slug = _safe_slug(f"{place_name}_{network_type}")
    elif bbox:
        slug = _safe_slug(f"{_bbox_slug(bbox)}_{network_type}")
    else:
        raise ValueError("place_name or bbox is required")
    return root / f"{slug}.graphml"


def _fixed_cache_path(*, cache_dir: str | Path, cache_filename: str) -> Path:
    # 固定地图缓存文件名不依赖用户输入；只允许简单文件名，避免意外写出缓存目录。
    filename = Path(cache_filename).name
    if not filename.endswith(".graphml"):
        filename = f"{filename}.graphml"
    root = Path(cache_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root / filename


def _graph_from_bbox(ox: Any, bbox: BoundingBox, network_type: str) -> nx.MultiDiGraph:
    # OSMnx 不同版本的 graph_from_bbox 参数顺序/签名不完全一致，这里兼容新旧 API。
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
    # travel_time 是后续 SNN delay/cost 的优先来源；若 OSMnx 估速失败则退化为 length。
    try:
        graph = ox.add_edge_speeds(graph)
        graph = ox.add_edge_travel_times(graph)
    except Exception:
        for _u, _v, _key, attrs in graph.edges(keys=True, data=True):
            attrs.setdefault("travel_time", attrs.get("length", 1.0))
    return graph


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # fallback loader 没有投影/几何库时，用球面距离估算相邻 OSM 节点间路段长度。
    radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return float(2 * radius_m * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _parse_speed_mps(value: Any, fallback_mps: float = 13.9) -> float:
    # OSM maxspeed 可能是 "50", "50 km/h", "30 mph" 或列表；统一解析成 m/s。
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
    # 手写 Overpass fallback 不支持行政边界裁剪，因此先用 Nominatim 把地名转为 bbox。
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
    # drive 模式下过滤明显非机动车道路；walk/bike/all 模式保留更多 highway 类型。
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

    # Overpass 查询 highway way，并用 (._;>;); 把这些道路引用的 node 一并取回。
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
    # Overpass 返回 node/way 混合列表；先拆成节点坐标表和道路 way 列表。
    for element in elements:
        if element.get("type") == "node":
            node_lookup[int(element["id"])] = {"x": float(element["lon"]), "y": float(element["lat"])}
        elif element.get("type") == "way":
            ways.append(element)

    graph = nx.MultiDiGraph()
    # OSM 原始 node id 保留为 MultiDiGraph 节点，后续 graph_adapter 再映射到连续整数。
    for node_id, attrs in node_lookup.items():
        graph.add_node(node_id, **attrs)

    for way in ways:
        tags = dict(way.get("tags") or {})
        if not _is_drive_way(tags, network_type):
            continue
        # way 是一串 OSM node；相邻 node 之间生成一条可通行边。
        nodes = [int(node) for node in way.get("nodes", []) if int(node) in node_lookup]
        if len(nodes) < 2:
            continue
        speed_mps = _parse_speed_mps(tags.get("maxspeed"))
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
                "oneway": False,
            }
            graph.add_edge(u, v, **edge_attrs)
            # 本项目演示场景默认所有机动车道路双向可通行，不保留 OSM oneway 限制。
            graph.add_edge(v, u, **edge_attrs)

    if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
        raise RuntimeError("Overpass returned no usable road edges; try a larger bbox.")
    graph.graph.update({"loader": "manual_overpass_fallback", "network_type": network_type})
    return graph


def _load_graphml(path: Path, ox: Any | None) -> nx.MultiDiGraph:
    # 优先使用 OSMnx 自带 GraphML 读写，失败时回退到 networkx 原生读写。
    if ox is not None:
        try:
            return ox.load_graphml(path)
        except Exception:
            pass
    return nx.read_graphml(path)


def _save_graphml(graph: nx.MultiDiGraph, path: Path, ox: Any | None) -> None:
    # 缓存保存的是 OSM MultiDiGraph，不是项目 DiGraph；这样下次仍保留原始 OSM 属性。
    path.parent.mkdir(parents=True, exist_ok=True)
    if ox is not None and graph.graph.get("loader") != "manual_overpass_fallback":
        ox.save_graphml(graph, path)
    else:
        nx.write_graphml(graph, path)


def _crop_graph_to_bbox(graph: nx.MultiDiGraph, bbox: BoundingBox) -> nx.MultiDiGraph:
    nodes = []
    for node, attrs in graph.nodes(data=True):
        try:
            lon = float(attrs.get("x"))
            lat = float(attrs.get("y"))
        except (TypeError, ValueError):
            continue
        if bbox.south <= lat <= bbox.north and bbox.west <= lon <= bbox.east:
            nodes.append(node)
    cropped = graph.subgraph(nodes).copy()
    if cropped.number_of_nodes() == 0 or cropped.number_of_edges() == 0:
        raise RuntimeError("legacy Hangzhou cache does not overlap the fixed bbox")
    cropped.graph.clear()
    cropped.graph.update(
        {
            key: value
            for key, value in graph.graph.items()
            if isinstance(value, (str, int, float, bool))
        }
    )
    cropped.graph["cropped_to_bbox"] = True
    cropped.graph["cropped_bbox_north"] = float(bbox.north)
    cropped.graph["cropped_bbox_south"] = float(bbox.south)
    cropped.graph["cropped_bbox_east"] = float(bbox.east)
    cropped.graph["cropped_bbox_west"] = float(bbox.west)
    return cropped


def load_osm_graph(
    *,
    place_name: str | None = None,
    bbox: BoundingBox | None = None,
    network_type: str = "drive",
    cache_dir: str | Path = "data/osm_cache",
    use_cache: bool = True,
    cache_filename: str | None = None,
) -> nx.MultiDiGraph:
    """Load a real road network from cache or OpenStreetMap.

    Exactly one of `place_name` or `bbox` should be provided. Downloaded maps
    are cached as GraphML and reused on later runs.
    """
    if bool(place_name) == bool(bbox):
        raise ValueError("provide exactly one of place_name or bbox")

    # 这里允许 OSMnx 不可用：只要 requests 可用，就可以走手写 Overpass fallback。
    try:
        ox = _import_osmnx()
    except RuntimeError:
        ox = None
    path = (
        _fixed_cache_path(cache_dir=cache_dir, cache_filename=cache_filename)
        if cache_filename
        else _cache_path(
            cache_dir=cache_dir,
            place_name=place_name,
            bbox=bbox,
            network_type=network_type,
        )
    )
    if use_cache and path.exists():
        # 缓存命中时不访问网络，便于离线演示和重复调试。
        return _load_graphml(path, ox)

    graph: nx.MultiDiGraph
    try:
        if ox is not None:
            try:
                if place_name:
                    # place 模式由 OSMnx 按地名/行政边界解析真实道路网络。
                    graph = ox.graph_from_place(place_name, network_type=network_type)
                else:
                    # bbox 模式只取矩形范围内道路，最适合控制 neuron 规模和 GUI 性能。
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


def load_hangzhou_graph(
    *,
    network_type: str = "drive",
    cache_dir: str | Path = "data/osm_cache",
    use_cache: bool = True,
) -> nx.MultiDiGraph:
    """Load the fixed Hangzhou road network, preferring a stable local cache."""
    fixed_cache = _fixed_cache_path(
        cache_dir=cache_dir,
        cache_filename=HANGZHOU_CACHE_FILENAME_TEMPLATE.format(network_type=network_type),
    )
    legacy_cache = _fixed_cache_path(cache_dir=cache_dir, cache_filename=f"hangzhou_{network_type}.graphml")
    if use_cache and not fixed_cache.exists() and legacy_cache.exists():
        try:
            ox = _import_osmnx()
        except RuntimeError:
            ox = None
        legacy_graph = _load_graphml(legacy_cache, ox)
        cropped = _crop_graph_to_bbox(legacy_graph, HANGZHOU_BBOX)
        _save_graphml(cropped, fixed_cache, ox)
        return cropped
    return load_osm_graph(
        bbox=HANGZHOU_BBOX,
        network_type=network_type,
        cache_dir=cache_dir,
        use_cache=use_cache,
        cache_filename=HANGZHOU_CACHE_FILENAME_TEMPLATE.format(network_type=network_type),
    )
