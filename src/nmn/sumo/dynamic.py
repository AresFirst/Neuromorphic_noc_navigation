"""Dynamic traffic helpers for SUMO-geometry navigation."""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import networkx as nx


GraphEdge = tuple[Any, Any]
Point2D = tuple[float, float]


@dataclass(slots=True)
class SumoTrafficVehicle:
    vehicle_id: str
    edge_source: Any
    edge_target: Any
    progress: float
    speed: float

    @property
    def edge(self) -> GraphEdge:
        return self.edge_source, self.edge_target

    def to_dict(self) -> dict:
        return asdict(self)


def _shape_length(shape: list | tuple) -> float:
    if len(shape) < 2:
        return 0.0
    total = 0.0
    for point_a, point_b in zip(shape, shape[1:]):
        total += math.hypot(float(point_b[0]) - float(point_a[0]), float(point_b[1]) - float(point_a[1]))
    return float(total)


def _edge_shape(G: nx.DiGraph, source: Any, target: Any) -> list[Point2D]:
    if not G.has_edge(source, target):
        return []
    attrs = G[source][target]
    shape = attrs.get("shape") or []
    if len(shape) >= 2:
        return [(float(point[0]), float(point[1])) for point in shape]

    source_attrs = G.nodes[source]
    target_attrs = G.nodes[target]
    if "x" in source_attrs and "y" in source_attrs and "x" in target_attrs and "y" in target_attrs:
        return [
            (float(source_attrs["x"]), float(source_attrs["y"])),
            (float(target_attrs["x"]), float(target_attrs["y"])),
        ]
    return []


def _interpolate_shape(shape: list[Point2D], progress: float) -> Point2D:
    if not shape:
        return 0.0, 0.0
    if len(shape) == 1:
        return float(shape[0][0]), float(shape[0][1])

    progress = max(0.0, min(1.0, float(progress)))
    total = _shape_length(shape)
    if total <= 0.0:
        return float(shape[-1][0]), float(shape[-1][1])
    target_distance = progress * total
    traversed = 0.0
    for point_a, point_b in zip(shape, shape[1:]):
        segment = math.hypot(float(point_b[0]) - float(point_a[0]), float(point_b[1]) - float(point_a[1]))
        if traversed + segment >= target_distance:
            local = (target_distance - traversed) / segment if segment > 0 else 0.0
            x = float(point_a[0]) + (float(point_b[0]) - float(point_a[0])) * local
            y = float(point_a[1]) + (float(point_b[1]) - float(point_a[1])) * local
            return x, y
        traversed += segment
    return float(shape[-1][0]), float(shape[-1][1])


def _candidate_edges(G: nx.DiGraph) -> list[GraphEdge]:
    candidates: list[GraphEdge] = []
    for source, target, attrs in G.edges(data=True):
        if attrs.get("state") == "blocked":
            continue
        if source == target:
            continue
        if len(attrs.get("shape") or []) >= 2 or ("x" in G.nodes[source] and "x" in G.nodes[target]):
            candidates.append((source, target))
    return candidates


def spawn_random_traffic_vehicles(
    G: nx.DiGraph,
    *,
    num_vehicles: int,
    seed: int = 0,
    min_speed: float = 0.18,
    max_speed: float = 0.42,
    num_hotspots: int = 0,
    hotspot_vehicle_fraction: float = 0.0,
) -> list[SumoTrafficVehicle]:
    """Create random background vehicles on graph edges.

    speed is stored as edge progress per traffic step. Hotspots intentionally
    concentrate part of the fleet to make congestion visible and reproducible.
    """
    if num_vehicles < 0:
        raise ValueError("num_vehicles must be non-negative")
    if min_speed <= 0 or max_speed <= 0 or max_speed < min_speed:
        raise ValueError("vehicle speed range must be positive and ordered")

    candidates = _candidate_edges(G)
    if not candidates or num_vehicles == 0:
        return []

    rng = random.Random(seed)
    hotspots: list[GraphEdge] = []
    if num_hotspots > 0:
        hotspots = rng.sample(candidates, min(int(num_hotspots), len(candidates)))

    hotspot_count = int(round(num_vehicles * max(0.0, min(1.0, hotspot_vehicle_fraction))))
    vehicles: list[SumoTrafficVehicle] = []
    for idx in range(num_vehicles):
        pool = hotspots if idx < hotspot_count and hotspots else candidates
        source, target = rng.choice(pool)
        vehicles.append(
            SumoTrafficVehicle(
                vehicle_id=f"veh_{idx:04d}",
                edge_source=source,
                edge_target=target,
                progress=rng.random(),
                speed=rng.uniform(float(min_speed), float(max_speed)),
            )
        )
    return vehicles


def advance_traffic_vehicles(
    G: nx.DiGraph,
    vehicles: list[SumoTrafficVehicle],
    *,
    seed: int,
) -> None:
    """Move vehicles along current edges and randomly choose next outgoing edges."""
    rng = random.Random(seed)
    for vehicle in vehicles:
        vehicle.progress += float(vehicle.speed)
        guard = 0
        while vehicle.progress >= 1.0 and guard < 4:
            guard += 1
            current_node = vehicle.edge_target
            outgoing = [
                (current_node, neighbor)
                for neighbor in G.successors(current_node)
                if G.has_edge(current_node, neighbor) and G[current_node][neighbor].get("state") != "blocked"
            ]
            if not outgoing:
                vehicle.progress = 0.99
                break
            vehicle.edge_source, vehicle.edge_target = rng.choice(outgoing)
            vehicle.progress -= 1.0
        vehicle.progress = max(0.0, min(0.999, float(vehicle.progress)))


def traffic_vehicle_positions(
    G: nx.DiGraph,
    vehicles: list[SumoTrafficVehicle],
) -> list[dict]:
    """Return vehicle positions in SUMO coordinates for drawing."""
    positions: list[dict] = []
    for vehicle in vehicles:
        shape = _edge_shape(G, vehicle.edge_source, vehicle.edge_target)
        x, y = _interpolate_shape(shape, vehicle.progress)
        edge_attrs = G[vehicle.edge_source][vehicle.edge_target] if G.has_edge(*vehicle.edge) else {}
        positions.append(
            {
                "vehicle_id": vehicle.vehicle_id,
                "x": float(x),
                "y": float(y),
                "graph_source": vehicle.edge_source,
                "graph_target": vehicle.edge_target,
                "sumo_edge_id": edge_attrs.get("sumo_edge_id"),
                "progress": float(vehicle.progress),
            }
        )
    return positions


def _edge_capacity(attrs: dict, vehicles_per_lane_capacity: float) -> float:
    lanes = attrs.get("lane_ids") or []
    num_lanes = max(1, len(lanes))
    return max(1.0, float(num_lanes) * float(vehicles_per_lane_capacity))


def _ensure_traffic_baseline(G: nx.DiGraph) -> None:
    for _source, _target, attrs in G.edges(data=True):
        original_delay = int(attrs.get("original_delay_ms", attrs.get("delay_ms", 1)))
        attrs["original_delay_ms"] = max(1, original_delay)
        attrs.setdefault("traffic_base_state", str(attrs.get("state", "normal")))
    for _node, attrs in G.nodes(data=True):
        attrs.setdefault("traffic_base_threshold_penalty", attrs.get("threshold_penalty", 0.0) or 0.0)


def apply_traffic_congestion(
    G: nx.DiGraph,
    vehicles: list[SumoTrafficVehicle],
    *,
    congested_density: float = 0.55,
    blocked_density: float = 1.0,
    delay_factor: float = 3.0,
    vehicles_per_lane_capacity: float = 3.0,
    threshold_penalty_ms: float = 2.0,
) -> dict:
    """Map vehicle density to edge delays, blocked states, and node penalties."""
    if congested_density < 0:
        raise ValueError("congested_density must be non-negative")
    if blocked_density <= congested_density:
        raise ValueError("blocked_density must be greater than congested_density")
    if delay_factor < 0:
        raise ValueError("delay_factor must be non-negative")
    if vehicles_per_lane_capacity <= 0:
        raise ValueError("vehicles_per_lane_capacity must be positive")
    if threshold_penalty_ms < 0:
        raise ValueError("threshold_penalty_ms must be non-negative")

    _ensure_traffic_baseline(G)
    for _source, _target, attrs in G.edges(data=True):
        attrs["delay_ms"] = int(attrs["original_delay_ms"])
        attrs["state"] = str(attrs.get("traffic_base_state", "normal"))
        attrs["traffic_density"] = 0.0
        attrs["traffic_vehicle_count"] = 0
    for _node, attrs in G.nodes(data=True):
        attrs["threshold_penalty"] = float(attrs.get("traffic_base_threshold_penalty", 0.0) or 0.0)
        attrs["traffic_threshold_delay_ms"] = 0

    counts: dict[GraphEdge, int] = {}
    for vehicle in vehicles:
        counts[vehicle.edge] = counts.get(vehicle.edge, 0) + 1

    congested_edges: list[GraphEdge] = []
    blocked_edges: list[GraphEdge] = []
    density_by_edge: dict[str, float] = {}

    for edge, count in counts.items():
        source, target = edge
        if not G.has_edge(source, target):
            continue
        attrs = G[source][target]
        density = float(count) / _edge_capacity(attrs, vehicles_per_lane_capacity)
        attrs["traffic_density"] = float(density)
        attrs["traffic_vehicle_count"] = int(count)
        density_by_edge[f"{source}->{target}"] = float(density)

        if density >= blocked_density:
            attrs["state"] = "blocked"
            blocked_edges.append(edge)
        elif density >= congested_density:
            original_delay = int(attrs["original_delay_ms"])
            attrs["delay_ms"] = max(1, int(round(original_delay * (1.0 + delay_factor * density))))
            attrs["state"] = "congested"
            congested_edges.append(edge)

        if density >= congested_density:
            node_attrs = G.nodes[target]
            penalty = max(
                float(node_attrs.get("threshold_penalty", 0.0) or 0.0),
                float(threshold_penalty_ms) * float(density),
            )
            node_attrs["threshold_penalty"] = penalty
            node_attrs["traffic_threshold_delay_ms"] = max(
                int(node_attrs.get("traffic_threshold_delay_ms", 0) or 0),
                int(round(penalty)),
            )

    for source, target, attrs in G.edges(data=True):
        if attrs.get("state") == "blocked":
            continue
        extra_delay = int(G.nodes[target].get("traffic_threshold_delay_ms", 0) or 0)
        if extra_delay > 0:
            attrs["delay_ms"] = max(1, int(attrs.get("delay_ms", attrs["original_delay_ms"])) + extra_delay)
            if attrs.get("state") == "normal":
                attrs["state"] = "congested"
                congested_edges.append((source, target))

    congested_edges = sorted(set(congested_edges))
    blocked_edges = sorted(set(blocked_edges))
    return {
        "congested_edges": congested_edges,
        "blocked_edges": blocked_edges,
        "density_by_edge": density_by_edge,
        "num_congested_edges": len(congested_edges),
        "num_blocked_edges": len(blocked_edges),
    }


def write_json(data: dict | list, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def write_gif(frame_paths: list[str | Path], save_path: str | Path, duration_ms: int = 180) -> bool:
    """Write an animated GIF from PNG frames when Pillow is available."""
    if not frame_paths:
        return False
    try:
        from PIL import Image
    except Exception:
        return False

    images = [Image.open(path).convert("P", palette=Image.Palette.ADAPTIVE) for path in frame_paths]
    output = Path(save_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    first, rest = images[0], images[1:]
    first.save(
        output,
        save_all=True,
        append_images=rest,
        duration=int(duration_ms),
        loop=0,
        optimize=False,
    )
    for image in images:
        image.close()
    return True


def wavefront_frame_times(wavefront_result: dict, num_frames: int) -> list[float]:
    """Choose monotonic wavefront times for animation frames."""
    if num_frames <= 0:
        return []
    spike_times = [float(value) for value in wavefront_result.get("spike_times_by_neuron", {}).values()]
    if not spike_times:
        return [0.0]
    max_time = max(spike_times)
    if num_frames == 1 or max_time <= 0.0:
        return [max_time]
    return [max_time * idx / float(num_frames - 1) for idx in range(num_frames)]
