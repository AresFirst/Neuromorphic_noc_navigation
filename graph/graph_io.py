"""图的 JSON 序列化 / 反序列化。

提供 NetworkX DiGraph 与 JSON 文件的双向转换，
以及通用结果字典的 JSON 持久化。

JSON 格式:
{
    "directed": true,
    "multigraph": false,
    "graph": {...},     // 图级元数据 (graph_type, seed 等)
    "nodes": [{"id": 0, "x": 0.5, "y": 0.3, "region": 1}, ...],
    "edges": [{"source": 0, "target": 1, "delay_ms": 5, ...}, ...]
}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx


def save_graph_json(G, path: str) -> None:
    """将 NetworkX 有向图导出为 JSON 文件。

    节点属性中的 "id" 作为节点标识符，其余属性保留。
    边属性中的 "source" / "target" 作为边标识符，其余属性保留。

    Args:
        G: NetworkX 有向图。
        path: 输出 JSON 文件路径（自动创建父目录）。
    """
    # 构建 JSON 负载结构
    payload = {
        "directed": bool(G.is_directed()),
        "multigraph": bool(G.is_multigraph()),
        "graph": dict(G.graph),
        "nodes": [],
        "edges": [],
    }
    for node, attrs in G.nodes(data=True):
        record = {"id": node}
        record.update(attrs)
        payload["nodes"].append(record)
    for source, target, attrs in G.edges(data=True):
        record = {"source": source, "target": target}
        record.update(attrs)
        payload["edges"].append(record)

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_graph_json(path: str) -> nx.DiGraph:
    """从 JSON 文件还原 NetworkX 有向图。

    Args:
        path: JSON 文件路径。

    Returns:
        NetworkX DiGraph，包含原图的所有节点/边属性和图级元数据。
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    G = nx.DiGraph()
    G.graph.update(payload.get("graph", {}))
    for node in payload.get("nodes", []):
        attrs = dict(node)
        node_id = attrs.pop("id")
        G.add_node(node_id, **attrs)
    for edge in payload.get("edges", []):
        attrs = dict(edge)
        source = attrs.pop("source")
        target = attrs.pop("target")
        G.add_edge(source, target, **attrs)
    return G


def save_results_json(data: dict, path: str) -> None:
    """将任意结果字典写入格式化的 JSON 文件。

    Args:
        data: 任意可 JSON 序列化的字典。
        path: 输出文件路径（自动创建父目录）。
    """
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
