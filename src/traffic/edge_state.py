"""Road-edge dynamic traffic state helpers.

这个模块负责给项目 DiGraph 的每条边补齐动态交通字段。字段直接写入
edge attributes，后续 SNN planner、动态路由器和 GUI 都读取同一份当前状态。
"""

from __future__ import annotations

import math
import re
from typing import Any

import networkx as nx

LOIHI_MIN_DELAY_MS = 1
LOIHI_MAX_DELAY_MS = 62


HIGHWAY_DEFAULTS: dict[str, tuple[float, float]] = {
    # value = (free_flow_speed_mps, capacity_veh_per_hour_per_lane)
    "motorway": (30.6, 2200.0),
    "motorway_link": (22.2, 1800.0),
    "trunk": (27.8, 2000.0),
    "trunk_link": (20.0, 1600.0),
    "primary": (16.7, 1500.0),
    "primary_link": (13.9, 1300.0),
    "secondary": (13.9, 1200.0),
    "secondary_link": (11.1, 1000.0),
    "tertiary": (11.1, 1000.0),
    "tertiary_link": (9.7, 900.0),
    "residential": (8.3, 700.0),
    "living_street": (4.2, 350.0),
    "service": (5.6, 500.0),
    "unclassified": (9.7, 800.0),
}
DEFAULT_SPEED_MPS = 11.1
DEFAULT_CAPACITY_PER_LANE = 900.0


def _first(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return value


def parse_highway(value: Any) -> str:
    """Return a normalized highway class used by default traffic parameters."""
    value = _first(value)
    if value is None:
        return "unclassified"
    text = str(value).strip().lower()
    return text or "unclassified"


def parse_lanes(value: Any, default: int = 1) -> int:
    """Parse OSM lanes values such as ``2``, ``2;3`` or ``['2']``."""
    value = _first(value)
    if value is None:
        return default
    match = re.search(r"\d+", str(value))
    if not match:
        return default
    return max(1, int(match.group(0)))


def parse_speed_mps(value: Any, fallback_mps: float) -> float:
    """Parse OSM speed values into meters per second."""
    value = _first(value)
    if value is None:
        return fallback_mps
    text = str(value).strip().lower()
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return fallback_mps
    speed = float(match.group(0))
    if "mph" in text:
        return max(0.1, speed * 0.44704)
    return max(0.1, speed / 3.6)


def highway_defaults(highway: Any) -> tuple[float, float]:
    """Return ``(speed_mps, capacity_per_lane)`` for a highway class."""
    key = parse_highway(highway)
    return HIGHWAY_DEFAULTS.get(key, (DEFAULT_SPEED_MPS, DEFAULT_CAPACITY_PER_LANE))


def clamp_delay_ms(value: float) -> int:
    """Encode travel time as a Loihi-compatible integer delay."""
    if not math.isfinite(float(value)):
        return LOIHI_MAX_DELAY_MS
    return min(LOIHI_MAX_DELAY_MS, max(LOIHI_MIN_DELAY_MS, int(round(float(value)))))


def initialize_edge_state(graph: nx.DiGraph, *, current_time: float = 0.0) -> nx.DiGraph:
    """Ensure every edge has the dynamic traffic fields required by the simulator.

    The function mutates and returns ``graph``. It does not inject future traffic:
    all dynamic fields start from free-flow conditions and are later updated by
    ``TrafficStateUpdater`` from the current vehicle distribution and active events.
    """
    for _u, _v, attrs in graph.edges(data=True):
        highway = attrs.get("highway", "unclassified")
        default_speed, default_capacity_per_lane = highway_defaults(highway)
        lanes = parse_lanes(attrs.get("lanes"), default=1)
        length = float(attrs.get("length", 1.0) or 1.0)
        length = max(1.0, length)

        free_flow_speed = parse_speed_mps(
            attrs.get("maxspeed", attrs.get("speed_kph")),
            float(attrs.get("free_flow_speed", default_speed) or default_speed),
        )
        free_flow_speed = max(0.1, float(free_flow_speed))
        free_flow_time = float(length / free_flow_speed)
        capacity = float(attrs.get("capacity", default_capacity_per_lane * lanes) or default_capacity_per_lane)
        capacity = max(1.0, capacity)

        attrs["length"] = length
        attrs["highway"] = parse_highway(highway)
        attrs["lanes"] = lanes
        attrs["free_flow_speed"] = free_flow_speed
        attrs["current_speed"] = float(attrs.get("current_speed", free_flow_speed) or free_flow_speed)
        attrs["free_flow_time"] = free_flow_time
        attrs["travel_time"] = float(attrs.get("travel_time", free_flow_time) or free_flow_time)
        attrs["capacity"] = capacity
        attrs["base_capacity"] = float(attrs.get("base_capacity", capacity) or capacity)
        attrs["base_free_flow_speed"] = float(attrs.get("base_free_flow_speed", free_flow_speed) or free_flow_speed)
        attrs["vehicle_count"] = int(attrs.get("vehicle_count", 0) or 0)
        attrs["density"] = float(attrs.get("density", 0.0) or 0.0)
        attrs["flow"] = float(attrs.get("flow", 0.0) or 0.0)
        attrs["congestion_level"] = float(attrs.get("congestion_level", 0.0) or 0.0)
        attrs["traffic_congestion"] = float(attrs["congestion_level"])
        attrs["last_updated_time"] = float(current_time)
        attrs["cost"] = float(attrs["travel_time"])
        attrs["delay_ms"] = clamp_delay_ms(float(attrs["travel_time"]))
        attrs["state"] = str(attrs.get("state", "normal"))
    return graph


def edge_travel_time(graph: nx.DiGraph, u: int, v: int, *, attr: str = "travel_time") -> float:
    """Read the current travel time for one edge with a safe fallback."""
    if not graph.has_edge(u, v):
        return math.inf
    attrs = graph[u][v]
    value = attrs.get(attr, attrs.get("free_flow_time", attrs.get("length", 1.0)))
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(attrs.get("length", 1.0) or 1.0)
    if not math.isfinite(parsed) or parsed <= 0.0:
        return 1.0
    return parsed


def route_eta(graph: nx.DiGraph, route: list[int], *, weight: str = "travel_time") -> float:
    """Compute ETA for a route using currently observable edge attributes."""
    if len(route) < 2:
        return 0.0
    total = 0.0
    for u, v in zip(route, route[1:]):
        total += edge_travel_time(graph, int(u), int(v), attr=weight)
    return float(total)
