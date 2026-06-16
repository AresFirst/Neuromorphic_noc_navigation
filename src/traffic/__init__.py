"""Simulated traffic congestion for dynamic SNN navigation."""

from __future__ import annotations

# 旧热点式接口仍保留，便于历史测试和外部脚本兼容；GUI 主线使用 SimulationEngine。
from .dynamic_router import DynamicRouter, DynamicRouterConfig, RerouteDecision, RoutePlan
from .edge_state import initialize_edge_state
from .flow_generator import FlowGenerator, FlowGeneratorConfig
from .incident_generator import IncidentGenerator, IncidentGeneratorConfig, TrafficIncident
from .metrics import MetricsRecorder, SimulationMetrics, baseline_dynamic_shortest_path, baseline_static_shortest_path
from .simulation_engine import SimulationEngine, SimulationEngineConfig, SimulationStepResult
from .simulator import TrafficConfig, apply_traffic_to_graph, generate_traffic_snapshot
from .state import TrafficEdgeState, TrafficSnapshot
from .serial_comparison import (
    CongestionScheduleItem,
    SerialNavigationComparison,
    SerialRouteRun,
    build_congestion_schedule,
    run_serial_navigation_comparison,
    run_serial_planning_round,
)
from .traffic_state_updater import TrafficStateUpdater, TrafficStateUpdaterConfig
from .vehicle import Vehicle, make_navigation_vehicle
from .vehicle_simulator import VehicleSimulator, VehicleSimulatorConfig

__all__ = [
    "DynamicRouter",
    "DynamicRouterConfig",
    "FlowGenerator",
    "FlowGeneratorConfig",
    "CongestionScheduleItem",
    "IncidentGenerator",
    "IncidentGeneratorConfig",
    "MetricsRecorder",
    "RerouteDecision",
    "RoutePlan",
    "SimulationEngine",
    "SimulationEngineConfig",
    "SimulationMetrics",
    "SimulationStepResult",
    "SerialNavigationComparison",
    "SerialRouteRun",
    "TrafficConfig",
    "TrafficEdgeState",
    "TrafficIncident",
    "TrafficSnapshot",
    "TrafficStateUpdater",
    "TrafficStateUpdaterConfig",
    "Vehicle",
    "VehicleSimulator",
    "VehicleSimulatorConfig",
    "apply_traffic_to_graph",
    "baseline_dynamic_shortest_path",
    "baseline_static_shortest_path",
    "build_congestion_schedule",
    "generate_traffic_snapshot",
    "initialize_edge_state",
    "make_navigation_vehicle",
    "run_serial_navigation_comparison",
    "run_serial_planning_round",
]
