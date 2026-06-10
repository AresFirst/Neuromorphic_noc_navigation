"""Update edge traffic state from current vehicles and active incidents."""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from .edge_state import clamp_delay_ms, initialize_edge_state
from .incident_generator import TrafficIncident
from .vehicle import Vehicle


@dataclass(frozen=True, slots=True)
class TrafficStateUpdaterConfig:
    alpha: float = 0.15
    beta: float = 4.0
    min_speed_fraction: float = 0.10
    congested_threshold: float = 0.70


class TrafficStateUpdater:
    """Apply BPR-style traffic dynamics to every road edge."""

    def __init__(self, config: TrafficStateUpdaterConfig | None = None) -> None:
        self.config = config or TrafficStateUpdaterConfig()

    def _incident_multipliers(
        self,
        incidents: list[TrafficIncident],
        current_time: float,
    ) -> dict[tuple[int, int], tuple[float, float, list[str]]]:
        multipliers: dict[tuple[int, int], tuple[float, float, list[str]]] = {}
        for incident in incidents:
            capacity_multiplier, speed_multiplier = incident.multipliers_at(current_time)
            for edge in incident.affected_edges:
                old_capacity, old_speed, event_ids = multipliers.get(edge, (1.0, 1.0, []))
                event_ids.append(incident.event_id)
                multipliers[edge] = (
                    old_capacity * float(capacity_multiplier),
                    old_speed * float(speed_multiplier),
                    event_ids,
                )
        return multipliers

    def update(
        self,
        graph: nx.DiGraph,
        vehicles: list[Vehicle],
        incidents: list[TrafficIncident],
        *,
        current_time: float,
        dt: float,
    ) -> nx.DiGraph:
        """Update graph edge attributes for the current timestep."""
        initialize_edge_state(graph, current_time=current_time)

        vehicle_counts: dict[tuple[int, int], int] = {}
        for vehicle in vehicles:
            edge = vehicle.current_edge
            if edge is None or vehicle.arrived:
                continue
            if graph.has_edge(*edge):
                vehicle_counts[edge] = vehicle_counts.get(edge, 0) + 1

        incident_multipliers = self._incident_multipliers(incidents, current_time)
        alpha = float(self.config.alpha)
        beta = float(self.config.beta)
        min_speed_fraction = max(0.01, float(self.config.min_speed_fraction))

        for u, v, attrs in graph.edges(data=True):
            edge = (int(u), int(v))
            vehicle_count = int(vehicle_counts.get(edge, 0))
            base_capacity = float(attrs.get("base_capacity", attrs.get("capacity", 1.0)) or 1.0)
            base_speed = float(attrs.get("base_free_flow_speed", attrs.get("free_flow_speed", 1.0)) or 1.0)
            length = max(1.0, float(attrs.get("length", 1.0) or 1.0))

            capacity_multiplier, speed_multiplier, event_ids = incident_multipliers.get(edge, (1.0, 1.0, []))
            capacity = max(1.0, base_capacity * float(capacity_multiplier))
            free_flow_speed = max(0.1, base_speed * float(speed_multiplier))
            free_flow_time = length / free_flow_speed

            previous_travel_time = max(1.0, float(attrs.get("travel_time", free_flow_time) or free_flow_time))
            # estimated_flow 是当前边上车辆按当前旅行时间折算的小时流量。
            estimated_flow = float(vehicle_count) * 3600.0 / previous_travel_time
            volume_capacity_ratio = max(0.0, estimated_flow / capacity)
            travel_time = free_flow_time * (1.0 + alpha * (volume_capacity_ratio ** beta))
            min_speed = max(0.1, free_flow_speed * min_speed_fraction)
            current_speed = max(min_speed, length / max(0.1, travel_time))
            travel_time = length / current_speed
            congestion_level = min(1.0, volume_capacity_ratio)

            attrs["free_flow_speed"] = free_flow_speed
            attrs["current_speed"] = current_speed
            attrs["free_flow_time"] = free_flow_time
            attrs["travel_time"] = travel_time
            attrs["capacity"] = capacity
            attrs["vehicle_count"] = vehicle_count
            attrs["density"] = float(vehicle_count) / length
            attrs["flow"] = estimated_flow
            attrs["volume_capacity_ratio"] = volume_capacity_ratio
            attrs["congestion_level"] = congestion_level
            attrs["traffic_congestion"] = congestion_level
            attrs["last_updated_time"] = float(current_time)
            attrs["active_incident_ids"] = ",".join(event_ids)
            attrs["cost"] = float(travel_time)
            attrs["delay_ms"] = clamp_delay_ms(float(travel_time))
            attrs["state"] = "congested" if congestion_level >= float(self.config.congested_threshold) else "normal"
        return graph
