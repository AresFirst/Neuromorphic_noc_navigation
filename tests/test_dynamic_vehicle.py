"""Tests for the dynamic ego vehicle."""

from __future__ import annotations

from nmn.dynamic.vehicle import EgoVehicle


def test_ego_vehicle_moves_along_route_and_reports_arrival():
    vehicle = EgoVehicle(start_node=0, target_node=5)
    vehicle.set_route([0, 1, 2, 5])

    state = vehicle.step()
    assert state["current_node"] == 1
    assert state["route_index"] == 1
    assert state["remaining_route"] == [1, 2, 5]
    assert state["arrived"] is False

    vehicle.step()
    state = vehicle.step()
    assert state["current_node"] == 5
    assert vehicle.has_arrived() is True

    final_state = vehicle.step()
    assert final_state["current_node"] == 5
    assert final_state["arrived"] is True


def test_ego_vehicle_set_route_overwrites_route():
    vehicle = EgoVehicle(start_node=0, target_node=5)
    vehicle.set_route([0, 1, 2, 5])
    vehicle.step()

    vehicle.set_route([2, 4, 5])
    assert vehicle.current_node() == 2
    assert vehicle.route == [2, 4, 5]
    assert vehicle.next_edge() == (2, 4)
