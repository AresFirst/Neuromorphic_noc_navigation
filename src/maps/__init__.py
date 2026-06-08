"""OSM map loading and graph adaptation helpers."""

from __future__ import annotations

# maps 包对外只暴露地图加载、图适配和坐标转换工具。
# GUI 和测试都应从这里导入稳定接口，避免直接依赖内部 helper。
from .graph_adapter import (
    edge_geometry_to_latlon,
    nearest_node_by_latlon,
    osmnx_multidigraph_to_digraph,
    path_edges,
    path_nodes_to_latlon,
)
from .osmnx_loader import BoundingBox, load_osm_graph

# __all__ 明确公共 API，便于后续重构内部文件时保持调用方稳定。
__all__ = [
    "BoundingBox",
    "edge_geometry_to_latlon",
    "load_osm_graph",
    "nearest_node_by_latlon",
    "osmnx_multidigraph_to_digraph",
    "path_edges",
    "path_nodes_to_latlon",
]
