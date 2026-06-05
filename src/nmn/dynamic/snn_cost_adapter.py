"""Adapt a dynamic road graph for SNN planning."""

from __future__ import annotations

import networkx as nx


def _positive_int(value: object, fallback: int) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        return int(fallback)
    return max(1, parsed)


def prepare_graph_for_snn_planning(
    G: nx.DiGraph,
    use_delay_penalty: bool = True,
    use_threshold_penalty: bool = True,
    min_delay_ms: int = 1,
    max_delay_ms: int | None = None,
) -> nx.DiGraph:
    if min_delay_ms < 1:
        raise ValueError("min_delay_ms must be positive")
    if max_delay_ms is not None and max_delay_ms < min_delay_ms:
        raise ValueError("max_delay_ms must be >= min_delay_ms")

    prepared = G.copy()
    for _node, attrs in prepared.nodes(data=True):
        if not use_threshold_penalty:
            attrs.pop("threshold_penalty", None)
        elif "threshold_penalty" in attrs:
            attrs["threshold_penalty"] = attrs["threshold_penalty"]

    for _u, _v, attrs in prepared.edges(data=True):
        state = str(attrs.get("state", "normal"))
        original_delay = attrs.get("original_delay_ms", attrs.get("delay_ms", min_delay_ms))
        if state == "blocked":
            delay_value = original_delay
        elif state == "congested" and use_delay_penalty:
            delay_value = attrs.get("delay_ms", original_delay)
        elif use_delay_penalty:
            delay_value = attrs.get("delay_ms", original_delay)
        else:
            delay_value = original_delay

        delay_ms = _positive_int(delay_value, min_delay_ms)
        delay_ms = max(min_delay_ms, delay_ms)
        if max_delay_ms is not None:
            delay_ms = min(delay_ms, int(max_delay_ms))

        attrs["delay_ms"] = int(delay_ms)
        if state == "blocked":
            attrs["state"] = "blocked"
        elif state == "congested":
            attrs["state"] = "congested"
        else:
            attrs["state"] = "normal"

    return prepared
