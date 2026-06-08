"""Deterministic simulated congestion for OSM road graphs."""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Iterable

import networkx as nx

from .state import TrafficEdgeState, TrafficSnapshot

LOIHI_MIN_DELAY_MS = 1
LOIHI_MAX_DELAY_MS = 62


@dataclass(frozen=True, slots=True)
class TrafficConfig:
    # 这些参数只控制模拟交通强度，不接入真实交通 API。
    vehicle_count: int = 80
    hotspot_count: int = 8
    congestion_strength: float = 2.5
    block_threshold: float = 0.92
    node_penalty_ms: int = 8
    seed: int = 7


def _stable_edge_score(edge: tuple[int, int], seed: int, step: int) -> float:
    # 使用 hash 而不是 random.shuffle，保证同一 seed/step/edge 在不同运行中结果稳定。
    raw = f"{seed}:{step}:{edge[0]}:{edge[1]}".encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:12]
    return int(digest, 16) / float(0xFFFFFFFFFFFF)


def _clamp_delay(value: float) -> int:
    # Loihi delay 必须落在 1..62；真实拥堵放大后的 cost 会另外保留。
    return min(LOIHI_MAX_DELAY_MS, max(LOIHI_MIN_DELAY_MS, int(round(value))))


def _path_hotspot_edges(path_edges: Iterable[tuple[int, int]], max_count: int) -> list[tuple[int, int]]:
    # 为了让“遇到拥堵后改路”在演示中明显，优先把热点放在当前路径中段。
    edges = [(int(u), int(v)) for u, v in path_edges]
    if not edges or max_count <= 0:
        return []
    midpoint = len(edges) // 2
    ordered = sorted(range(len(edges)), key=lambda idx: abs(idx - midpoint))
    return [edges[idx] for idx in ordered[:max_count]]


def _random_hotspot_edges(graph: nx.DiGraph, count: int, seed: int, step: int) -> list[tuple[int, int]]:
    # 没有当前路径或还需要更多热点时，在全图中按稳定分数选边。
    edges = [(int(u), int(v)) for u, v in graph.edges()]
    ranked = sorted(edges, key=lambda edge: _stable_edge_score(edge, seed, step), reverse=True)
    return ranked[: max(0, count)]


def _edge_congestion(edge: tuple[int, int], rank: int, hotspot_count: int, config: TrafficConfig, step: int) -> float:
    # 拥堵强度由热点排名、车辆压力和一个随 step 变化的小波动共同决定。
    rank_weight = 1.0 - (rank / max(1, hotspot_count + 1))
    wave = 0.15 * math.sin((step + rank + edge[0] + edge[1]) * 0.73)
    vehicle_pressure = min(1.0, max(0.0, config.vehicle_count / 120.0))
    return max(0.0, min(1.0, 0.45 + 0.45 * rank_weight + 0.25 * vehicle_pressure + wave))


def generate_traffic_snapshot(
    graph: nx.DiGraph,
    *,
    step: int,
    config: TrafficConfig | None = None,
    route_edges: Iterable[tuple[int, int]] | None = None,
    prefer_route: bool = True,
) -> TrafficSnapshot:
    """Create a deterministic simulated traffic snapshot.

    When `route_edges` is provided, the simulator places part of the congestion
    on the current route. This makes rerouting visible without external APIs.
    """
    cfg = config or TrafficConfig()
    # hotspot_count 不允许超过图中边数，否则小图测试会产生无效热点。
    hotspot_count = min(max(0, int(cfg.hotspot_count)), graph.number_of_edges())
    # prefer_route=True 时，先从旧路径里选一部分拥堵边，再用全图随机热点补足。
    route_hotspots = _path_hotspot_edges(route_edges or [], max(1, hotspot_count // 2)) if prefer_route else []
    remaining = max(0, hotspot_count - len(route_hotspots))
    random_hotspots = _random_hotspot_edges(graph, remaining + len(route_hotspots), cfg.seed, int(step))

    hotspots: list[tuple[int, int]] = []
    # 去重并过滤已经不存在的边，避免交通状态引用到当前图没有的 edge。
    for edge in [*route_hotspots, *random_hotspots]:
        if edge in graph.edges and edge not in hotspots:
            hotspots.append(edge)
        if len(hotspots) >= hotspot_count:
            break

    rng = random.Random(cfg.seed + int(step) * 9973)
    edge_states: dict[tuple[int, int], TrafficEdgeState] = {}
    inhibited_nodes: dict[int, float] = {}
    for rank, edge in enumerate(hotspots):
        congestion = _edge_congestion(edge, rank, hotspot_count, cfg, int(step))
        if edge in route_hotspots:
            # 当前路径上的拥堵略微增强，便于在 GUI 中观察 reroute。
            congestion = min(1.0, congestion + 0.18)
        delay_factor = 1.0 + float(cfg.congestion_strength) * congestion
        blocked = congestion >= float(cfg.block_threshold)
        vehicle_count = max(1, int(round(2 + congestion * max(1, cfg.vehicle_count / max(1, hotspot_count)))))
        if rng.random() < 0.08 and edge not in route_hotspots:
            # 少量随机热点不阻塞，只变慢，让交通层不至于每次都把图切断。
            blocked = False
        state = TrafficEdgeState(
            edge=edge,
            vehicle_count=vehicle_count,
            congestion=float(congestion),
            delay_factor=float(delay_factor),
            blocked=bool(blocked),
        )
        edge_states[edge] = state
        target = int(edge[1])
        # 把拥堵边的下游节点视为受影响路口，后续转化为进入该节点的延迟惩罚。
        inhibited_nodes[target] = max(inhibited_nodes.get(target, 0.0), congestion)

    return TrafficSnapshot(
        step=int(step),
        edge_states=edge_states,
        inhibited_nodes=inhibited_nodes,
        metadata={
            "vehicle_count": int(cfg.vehicle_count),
            "hotspot_count": int(hotspot_count),
            "congestion_strength": float(cfg.congestion_strength),
            "block_threshold": float(cfg.block_threshold),
            "node_penalty_ms": int(cfg.node_penalty_ms),
        },
    )


def apply_traffic_to_graph(
    base_graph: nx.DiGraph,
    snapshot: TrafficSnapshot | None,
    *,
    config: TrafficConfig | None = None,
) -> nx.DiGraph:
    """Return a dynamic graph with simulated congestion applied."""
    cfg = config or TrafficConfig()
    # 必须 copy：模拟交通只生成临时 planning_graph，不能污染原始 OSM base_graph。
    graph = base_graph.copy()
    if snapshot is None:
        # 没有交通快照时也写入 base_*，让后续多次交通 step 都能从原始值恢复。
        for _u, _v, attrs in graph.edges(data=True):
            attrs.setdefault("base_cost", float(attrs.get("cost", 1.0) or 1.0))
            attrs.setdefault("base_delay_ms", int(attrs.get("delay_ms", 1) or 1))
            attrs.setdefault("base_travel_time", float(attrs.get("travel_time", attrs.get("cost", 1.0)) or 1.0))
        return graph

    # 先把所有边重置为 base 状态，再叠加当前 snapshot，避免 delay 在多次 step 中累加。
    for u, v, attrs in graph.edges(data=True):
        base_cost = float(attrs.get("base_cost", attrs.get("cost", 1.0)) or 1.0)
        base_delay = int(attrs.get("base_delay_ms", attrs.get("delay_ms", 1)) or 1)
        base_travel_time = float(attrs.get("base_travel_time", attrs.get("travel_time", base_cost)) or base_cost)

        attrs["base_cost"] = base_cost
        attrs["base_delay_ms"] = base_delay
        attrs["base_travel_time"] = base_travel_time
        attrs["traffic_congestion"] = 0.0
        attrs["vehicle_count"] = 0
        attrs["delay_factor"] = 1.0
        attrs["node_penalty_ms"] = 0
        attrs["state"] = "normal"
        attrs["cost"] = base_cost
        attrs["travel_time"] = base_travel_time
        attrs["delay_ms"] = _clamp_delay(base_delay)

    # 边级拥堵：直接放大 cost/travel_time/delay_ms，并按阈值标记 blocked。
    for edge, state in snapshot.edge_states.items():
        if not graph.has_edge(*edge):
            continue
        attrs = graph[edge[0]][edge[1]]
        base_cost = float(attrs.get("base_cost", attrs.get("cost", 1.0)) or 1.0)
        base_delay = int(attrs.get("base_delay_ms", attrs.get("delay_ms", 1)) or 1)
        base_travel_time = float(attrs.get("base_travel_time", attrs.get("travel_time", base_cost)) or base_cost)
        attrs["traffic_congestion"] = float(state.congestion)
        attrs["vehicle_count"] = int(state.vehicle_count)
        attrs["delay_factor"] = float(state.delay_factor)
        attrs["cost"] = float(base_cost * state.delay_factor)
        attrs["travel_time"] = float(base_travel_time * state.delay_factor)
        attrs["delay_ms"] = _clamp_delay(base_delay * state.delay_factor)
        attrs["state"] = "blocked" if state.blocked else "congested"

    # 节点级抑制：不直接改 neuron threshold，而是给所有进入该节点的边增加 delay/cost。
    for node, congestion in snapshot.inhibited_nodes.items():
        penalty = int(round(float(cfg.node_penalty_ms) * float(congestion)))
        if penalty <= 0:
            continue
        for predecessor in graph.predecessors(node):
            attrs = graph[predecessor][node]
            if attrs.get("state") == "blocked":
                continue
            attrs["node_penalty_ms"] = max(int(attrs.get("node_penalty_ms", 0) or 0), penalty)
            attrs["delay_ms"] = _clamp_delay(int(attrs.get("delay_ms", 1) or 1) + penalty)
            attrs["cost"] = float(attrs.get("cost", 1.0) or 1.0) + float(penalty)
            if attrs.get("state") == "normal":
                attrs["state"] = "node_penalty"

    # 图级元数据用于 GUI 统计和 JSON 调试，不参与 wavefront 计算。
    graph.graph["traffic_snapshot_step"] = int(snapshot.step)
    graph.graph["traffic_blocked_edges"] = sorted(snapshot.blocked_edges)
    graph.graph["traffic_congested_edges"] = sorted(snapshot.congested_edges)
    graph.graph["traffic_inhibited_nodes"] = dict(snapshot.inhibited_nodes)
    return graph
