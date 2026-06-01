from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx


def save_graph_json(G, path: str) -> None:
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
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
