from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_stdp_trace_table(
    G,
    parent_trace: dict[int, int | None],
    spike_times_by_neuron: dict[int, float],
    delay_attr: str = "delay_ms",
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for pre, post, attrs in G.edges(data=True):
        if pre not in spike_times_by_neuron and post not in spike_times_by_neuron:
            continue

        is_parent_edge = parent_trace.get(post) == pre
        pre_time = spike_times_by_neuron.get(pre)
        post_time = spike_times_by_neuron.get(post)
        delta_t = None
        if pre_time is not None and post_time is not None:
            delta_t = float(post_time) - float(pre_time)

        rows.append(
            {
                "pre": int(pre),
                "post": int(post),
                "is_parent_edge": bool(is_parent_edge),
                "pre_spike_time_ms": None if pre_time is None else float(pre_time),
                "post_spike_time_ms": None if post_time is None else float(post_time),
                "delta_t_ms": delta_t,
                "stdp_weight": 1.0 if is_parent_edge else 0.0,
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            "pre",
            "post",
            "is_parent_edge",
            "pre_spike_time_ms",
            "post_spike_time_ms",
            "delta_t_ms",
            "stdp_weight",
        ],
    )
