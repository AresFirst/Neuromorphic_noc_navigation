"""Vehicle state models for dynamic traffic simulation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Vehicle:
    """A background or navigation vehicle moving along a node route."""

    vehicle_id: str
    origin: int
    destination: int
    departure_time: float
    route: list[int]
    current_edge_index: int = 0
    position_on_edge: float = 0.0
    is_background_vehicle: bool = True
    allow_reroute: bool = False
    arrived: bool = False
    arrival_time: float | None = None
    total_distance: float = 0.0
    last_reroute_time: float = -1.0e9
    metadata: dict[str, float | int | str | bool] = field(default_factory=dict)

    @property
    def current_edge(self) -> tuple[int, int] | None:
        if self.arrived or self.current_edge_index >= len(self.route) - 1:
            return None
        return int(self.route[self.current_edge_index]), int(self.route[self.current_edge_index + 1])

    @property
    def current_node(self) -> int:
        if not self.route:
            return int(self.destination)
        if self.current_edge_index >= len(self.route):
            return int(self.route[-1])
        return int(self.route[self.current_edge_index])

    @property
    def current_edge_end(self) -> int:
        edge = self.current_edge
        if edge is None:
            return int(self.destination)
        return int(edge[1])

    @property
    def travel_time(self) -> float | None:
        if self.arrival_time is None:
            return None
        return float(self.arrival_time - self.departure_time)

    def replace_remaining_route(self, route_from_edge_end: list[int], *, current_time: float) -> None:
        """Replace the route after the current edge without teleporting the vehicle."""
        edge = self.current_edge
        if edge is None:
            self.route = [self.current_node, *route_from_edge_end[1:]] if route_from_edge_end else [self.current_node]
            self.current_edge_index = 0
        else:
            current_u, current_v = edge
            if route_from_edge_end and int(route_from_edge_end[0]) == current_v:
                self.route = [current_u, *[int(node) for node in route_from_edge_end]]
                self.current_edge_index = 0
            else:
                self.route = [current_u, current_v]
                self.current_edge_index = 0
        self.last_reroute_time = float(current_time)


def make_navigation_vehicle(vehicle_id: str, origin: int, destination: int, route: list[int], departure_time: float) -> Vehicle:
    """Create the single user-facing navigation vehicle."""
    return Vehicle(
        vehicle_id=vehicle_id,
        origin=int(origin),
        destination=int(destination),
        departure_time=float(departure_time),
        route=[int(node) for node in route],
        is_background_vehicle=False,
        allow_reroute=True,
        last_reroute_time=float(departure_time),
    )
