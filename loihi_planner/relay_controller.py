from __future__ import annotations

import networkx as nx


class RelayController:
    def __init__(self, G: nx.DiGraph):
        self._graph = G.copy()
        for _u, _v, attrs in self._graph.edges(data=True):
            if "original_delay_ms" not in attrs:
                attrs["original_delay_ms"] = int(attrs.get("delay_ms", 1))

    def _edge_attrs(self, u: int, v: int) -> dict:
        if not self._graph.has_edge(u, v):
            raise ValueError(f"edge ({u}, {v}) does not exist")
        return self._graph[u][v]

    def block_edge(self, u: int, v: int) -> None:
        attrs = self._edge_attrs(u, v)
        attrs["state"] = "blocked"

    def penalize_edge(self, u: int, v: int, factor: float) -> None:
        if factor <= 0:
            raise ValueError("factor must be positive")
        attrs = self._edge_attrs(u, v)
        original_delay_ms = int(attrs.get("original_delay_ms", attrs.get("delay_ms", 1)))
        attrs["original_delay_ms"] = original_delay_ms
        attrs["delay_ms"] = max(1, int(round(original_delay_ms * float(factor))))
        attrs["state"] = "penalized"

    def restore_edge(self, u: int, v: int) -> None:
        attrs = self._edge_attrs(u, v)
        original_delay_ms = int(attrs.get("original_delay_ms", attrs.get("delay_ms", 1)))
        attrs["delay_ms"] = original_delay_ms
        attrs["original_delay_ms"] = original_delay_ms
        attrs["state"] = "normal"

    def get_graph(self) -> nx.DiGraph:
        return self._graph
