"""Runtime congestion events and controller."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import asdict, dataclass

import networkx as nx


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CongestionEvent:
    edge_u: int
    edge_v: int
    start_step: int
    end_step: int
    delay_factor: float = 5.0
    threshold_penalty: float = 0.0
    mode: str = "delay"

    def __post_init__(self) -> None:
        self.edge_u = int(self.edge_u)
        self.edge_v = int(self.edge_v)
        self.start_step = int(self.start_step)
        self.end_step = int(self.end_step)
        self.delay_factor = float(self.delay_factor)
        self.threshold_penalty = float(self.threshold_penalty)
        self.mode = str(self.mode)

        if self.end_step <= self.start_step:
            raise ValueError("end_step must be greater than start_step")
        if self.delay_factor <= 0:
            raise ValueError("delay_factor must be positive")
        if self.threshold_penalty < 0:
            raise ValueError("threshold_penalty must be non-negative")
        if self.mode not in {"delay", "blocked", "threshold"}:
            raise ValueError("mode must be one of: delay, blocked, threshold")

    def is_active(self, step: int) -> bool:
        return self.start_step <= int(step) < self.end_step

    def to_dict(self) -> dict:
        return asdict(self)


class CongestionController:
    def __init__(self, G: nx.DiGraph):
        self._graph = G.copy()
        self._events: list[CongestionEvent] = []
        self._warned_missing_edges: set[tuple[int, int]] = set()
        self._active_edges: list[tuple[int, int]] = []
        self._edge_original_delay: dict[tuple[int, int], int] = {}
        self._node_original_penalty: dict[int, float | int | None] = {}

        for u, v, attrs in self._graph.edges(data=True):
            original_delay = int(attrs.get("original_delay_ms", attrs.get("delay_ms", 1)))
            original_delay = max(1, original_delay)
            attrs["original_delay_ms"] = int(original_delay)
            attrs["delay_ms"] = max(1, int(attrs.get("delay_ms", original_delay)))
            attrs["state"] = str(attrs.get("state", "normal"))
            self._edge_original_delay[(int(u), int(v))] = int(original_delay)

        for node, attrs in self._graph.nodes(data=True):
            self._node_original_penalty[int(node)] = attrs.get("threshold_penalty")

    def add_event(self, event: CongestionEvent) -> None:
        self._events.append(event)

    def _restore_baseline(self) -> None:
        for (u, v), original_delay in self._edge_original_delay.items():
            attrs = self._graph[u][v]
            attrs["delay_ms"] = int(original_delay)
            attrs["state"] = "normal"
        for node, original_penalty in self._node_original_penalty.items():
            attrs = self._graph.nodes[node]
            if original_penalty is None:
                attrs.pop("threshold_penalty", None)
            else:
                attrs["threshold_penalty"] = original_penalty

    def update(self, step: int) -> dict:
        step = int(step)
        self._restore_baseline()

        active_events = [event for event in self._events if event.is_active(step)]
        active_edges: set[tuple[int, int]] = set()
        blocked_edges: dict[tuple[int, int], list[CongestionEvent]] = defaultdict(list)
        delay_edges: dict[tuple[int, int], list[CongestionEvent]] = defaultdict(list)
        threshold_events: dict[int, list[CongestionEvent]] = defaultdict(list)

        for event in active_events:
            edge = (event.edge_u, event.edge_v)
            if not self._graph.has_edge(*edge):
                if edge not in self._warned_missing_edges:
                    logger.warning("Ignoring congestion event for missing edge %s->%s", edge[0], edge[1])
                    self._warned_missing_edges.add(edge)
                continue
            active_edges.add(edge)
            if event.mode == "blocked":
                blocked_edges[edge].append(event)
            elif event.mode == "delay":
                delay_edges[edge].append(event)
            elif event.mode == "threshold":
                threshold_events[event.edge_v].append(event)

        for (u, v), events in delay_edges.items():
            original_delay = self._edge_original_delay[(u, v)]
            delay_factor = max(event.delay_factor for event in events)
            attrs = self._graph[u][v]
            attrs["delay_ms"] = max(1, int(round(float(original_delay) * float(delay_factor))))
            attrs["state"] = "congested"

        for (u, v) in blocked_edges:
            attrs = self._graph[u][v]
            attrs["state"] = "blocked"

        for node, events in threshold_events.items():
            attrs = self._graph.nodes[node]
            penalty = float(attrs.get("threshold_penalty", 0.0) or 0.0)
            penalty += sum(float(event.threshold_penalty) for event in events)
            attrs["threshold_penalty"] = penalty

        previous_active = set(self._active_edges)
        self._active_edges = sorted(active_edges)
        activated_edges = sorted(active_edges - previous_active)
        deactivated_edges = sorted(previous_active - active_edges)
        return {
            "activated_edges": activated_edges,
            "deactivated_edges": deactivated_edges,
            "active_edges": list(self._active_edges),
        }

    def get_graph(self) -> nx.DiGraph:
        return self._graph

    def active_congested_edges(self) -> list[tuple[int, int]]:
        return list(self._active_edges)
