"""Runtime incident generation without future-information leakage."""

from __future__ import annotations

import random
from dataclasses import dataclass

import networkx as nx


@dataclass(slots=True)
class TrafficIncident:
    event_id: str
    event_type: str
    affected_edges: list[tuple[int, int]]
    start_time: float
    end_time: float
    capacity_multiplier: float
    speed_multiplier: float
    is_active: bool = True

    def multipliers_at(self, current_time: float) -> tuple[float, float]:
        """Return capacity/speed multipliers with gradual recovery near the end."""
        if current_time < self.start_time or current_time >= self.end_time:
            return 1.0, 1.0
        duration = max(1.0, self.end_time - self.start_time)
        recovery_window = min(60.0, duration * 0.25)
        recovery_start = self.end_time - recovery_window
        if current_time <= recovery_start:
            return float(self.capacity_multiplier), float(self.speed_multiplier)
        progress = (float(current_time) - recovery_start) / max(1.0, recovery_window)
        capacity = float(self.capacity_multiplier) + (1.0 - float(self.capacity_multiplier)) * progress
        speed = float(self.speed_multiplier) + (1.0 - float(self.speed_multiplier)) * progress
        return max(0.01, capacity), max(0.01, speed)


@dataclass(frozen=True, slots=True)
class IncidentGeneratorConfig:
    incident_probability_per_minute: float = 0.05
    incident_duration_min_seconds: float = 120.0
    incident_duration_max_seconds: float = 300.0
    capacity_drop_min: float = 0.20
    capacity_drop_max: float = 0.50
    random_seed: int = 7


class IncidentGenerator:
    """Create incidents during the simulation loop.

    The generator keeps random state internally, but it does not publish future
    incidents. DynamicRouter only sees edge attributes after TrafficStateUpdater
    applies currently active incidents.
    """

    def __init__(self, config: IncidentGeneratorConfig | None = None) -> None:
        self.config = config or IncidentGeneratorConfig()
        self.rng = random.Random(self.config.random_seed)
        self.incidents: list[TrafficIncident] = []
        self._counter = 0

    def _choose_edge(self, graph: nx.DiGraph) -> tuple[int, int] | None:
        edges = [(int(u), int(v), attrs) for u, v, attrs in graph.edges(data=True)]
        if not edges:
            return None
        ranked = sorted(edges, key=lambda item: float(item[2].get("flow", 0.0) or 0.0), reverse=True)
        high_flow = [edge for edge in ranked[: max(1, min(20, len(ranked) // 5 or 1))]]
        u, v, _attrs = self.rng.choice(high_flow if high_flow else ranked)
        return int(u), int(v)

    def _affected_edges(self, graph: nx.DiGraph, edge: tuple[int, int]) -> list[tuple[int, int]]:
        affected = [edge]
        # 局部事故可能影响下游一条边，但只使用当前图拓扑，不预设未来拥堵。
        downstream = [(int(edge[1]), int(v)) for v in graph.successors(edge[1]) if graph.has_edge(edge[1], v)]
        if downstream and self.rng.random() < 0.45:
            affected.append(self.rng.choice(downstream))
        return affected

    def _new_incident(self, graph: nx.DiGraph, current_time: float) -> TrafficIncident | None:
        edge = self._choose_edge(graph)
        if edge is None:
            return None
        duration = self.rng.uniform(
            float(self.config.incident_duration_min_seconds),
            float(self.config.incident_duration_max_seconds),
        )
        event_type = "accident" if self.rng.random() < 0.65 else "roadwork"
        capacity_multiplier = self.rng.uniform(float(self.config.capacity_drop_min), float(self.config.capacity_drop_max))
        speed_multiplier = self.rng.uniform(0.25, 0.65) if event_type == "accident" else self.rng.uniform(0.45, 0.80)
        self._counter += 1
        return TrafficIncident(
            event_id=f"incident-{self._counter}",
            event_type=event_type,
            affected_edges=self._affected_edges(graph, edge),
            start_time=float(current_time),
            end_time=float(current_time + duration),
            capacity_multiplier=float(capacity_multiplier),
            speed_multiplier=float(speed_multiplier),
            is_active=True,
        )

    def step(self, graph: nx.DiGraph, *, current_time: float, dt: float) -> list[TrafficIncident]:
        """Advance incident state and maybe trigger one new incident now."""
        for incident in self.incidents:
            if incident.is_active and current_time >= incident.end_time:
                incident.is_active = False

        probability = max(0.0, float(self.config.incident_probability_per_minute)) * max(0.0, float(dt)) / 60.0
        if self.rng.random() < probability:
            incident = self._new_incident(graph, current_time)
            if incident is not None:
                self.incidents.append(incident)

        return self.active_incidents(current_time)

    def active_incidents(self, current_time: float) -> list[TrafficIncident]:
        return [
            incident
            for incident in self.incidents
            if incident.is_active and incident.start_time <= current_time < incident.end_time
        ]
