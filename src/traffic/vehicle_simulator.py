"""Move vehicles through the currently observable traffic graph."""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from .vehicle import Vehicle


@dataclass(frozen=True, slots=True)
class VehicleSimulatorConfig:
    background_reroute_interval: float = 45.0


class VehicleSimulator:
    """Advance background and navigation vehicles along their routes."""

    def __init__(self, config: VehicleSimulatorConfig | None = None) -> None:
        self.config = config or VehicleSimulatorConfig()

    def _maybe_reroute_background(self, graph: nx.DiGraph, vehicle: Vehicle, current_time: float) -> None:
        if not vehicle.allow_reroute or vehicle.arrived or not vehicle.is_background_vehicle:
            return
        if current_time - float(vehicle.last_reroute_time) < float(self.config.background_reroute_interval):
            return
        node = vehicle.current_node
        if node == vehicle.destination or node not in graph or vehicle.destination not in graph:
            return
        try:
            route = [int(item) for item in nx.shortest_path(graph, node, vehicle.destination, weight="travel_time")]
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return
        if len(route) >= 2:
            vehicle.route = route
            vehicle.current_edge_index = 0
            vehicle.position_on_edge = 0.0
            vehicle.last_reroute_time = float(current_time)

    def move(self, graph: nx.DiGraph, vehicles: list[Vehicle], *, current_time: float, dt: float) -> list[Vehicle]:
        """Move vehicles by ``dt`` seconds and return vehicles still in the network."""
        active: list[Vehicle] = []
        for vehicle in vehicles:
            if vehicle.arrived:
                continue
            remaining_time = max(0.0, float(dt))
            while remaining_time > 1.0e-9 and not vehicle.arrived:
                edge = vehicle.current_edge
                if edge is None:
                    vehicle.arrived = True
                    vehicle.arrival_time = float(current_time)
                    break
                u, v = edge
                if not graph.has_edge(u, v):
                    vehicle.arrived = True
                    vehicle.arrival_time = float(current_time)
                    break

                attrs = graph[u][v]
                length = max(1.0, float(attrs.get("length", 1.0) or 1.0))
                speed = max(0.1, float(attrs.get("current_speed", attrs.get("free_flow_speed", 1.0)) or 1.0))
                distance_to_end = max(0.0, length - float(vehicle.position_on_edge))
                time_to_end = distance_to_end / speed
                if time_to_end > remaining_time:
                    distance = speed * remaining_time
                    vehicle.position_on_edge += distance
                    vehicle.total_distance += distance
                    remaining_time = 0.0
                else:
                    vehicle.total_distance += distance_to_end
                    remaining_time -= time_to_end
                    vehicle.current_edge_index += 1
                    vehicle.position_on_edge = 0.0
                    if vehicle.current_edge_index >= len(vehicle.route) - 1:
                        vehicle.arrived = True
                        vehicle.arrival_time = float(current_time + max(0.0, float(dt) - remaining_time))
                        break
                    self._maybe_reroute_background(graph, vehicle, current_time)

            if not vehicle.arrived:
                active.append(vehicle)
        return active
