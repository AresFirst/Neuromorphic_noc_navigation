from __future__ import annotations

import pandas as pd


PACKET_COLUMNS = [
    "cycle",
    "src_neuron",
    "dst_neuron",
    "src_core",
    "dst_core",
    "packet_type",
    "packet_size",
]


def spike_trace_to_packet_trace(
    G,
    spike_times_by_neuron: dict[int, float],
    core_mapping: dict[int, int],
    delay_attr: str = "delay_ms",
    tolerance_ms: float = 1.0,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    spike_times = {int(node): float(time) for node, time in spike_times_by_neuron.items()}

    for src, dst, attrs in G.edges(data=True):
        src = int(src)
        dst = int(dst)
        if attrs.get("state") == "blocked":
            continue
        if src not in spike_times or dst not in spike_times:
            continue
        delay = int(attrs.get(delay_attr, 0))
        if delay <= 0:
            continue
        predicted = spike_times[src] + float(delay)
        if abs(predicted - spike_times[dst]) <= float(tolerance_ms):
            rows.append(
                {
                    "cycle": int(round(spike_times[src])),
                    "src_neuron": src,
                    "dst_neuron": dst,
                    "src_core": int(core_mapping[src]),
                    "dst_core": int(core_mapping[dst]),
                    "packet_type": "spike",
                    "packet_size": 1,
                }
            )

    return pd.DataFrame(rows, columns=PACKET_COLUMNS).sort_values(
        ["cycle", "src_neuron", "dst_neuron"], ignore_index=True
    )


def relay_events_to_packet_trace(
    relay_events: list[dict],
    core_mapping: dict[int, int],
    relay_core: int = 0,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for event in relay_events:
        cycle = int(event.get("cycle", 0))
        edge_u = int(event["edge_u"])
        edge_v = int(event["edge_v"])
        for node in (edge_u, edge_v):
            rows.append(
                {
                    "cycle": cycle,
                    "src_neuron": -1,
                    "dst_neuron": node,
                    "src_core": int(relay_core),
                    "dst_core": int(core_mapping[node]),
                    "packet_type": "relay",
                    "packet_size": 1,
                }
            )
    return pd.DataFrame(rows, columns=PACKET_COLUMNS).sort_values(
        ["cycle", "dst_neuron"], ignore_index=True
    )
