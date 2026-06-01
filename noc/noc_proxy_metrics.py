from __future__ import annotations

from collections import Counter

import pandas as pd


def core_id_to_xy(core_id: int, mesh_cols: int) -> tuple[int, int]:
    if mesh_cols <= 0:
        raise ValueError("mesh_cols must be positive")
    return int(core_id % mesh_cols), int(core_id // mesh_cols)


def manhattan_hop(src_core: int, dst_core: int, mesh_cols: int) -> int:
    src_x, src_y = core_id_to_xy(src_core, mesh_cols)
    dst_x, dst_y = core_id_to_xy(dst_core, mesh_cols)
    return int(abs(src_x - dst_x) + abs(src_y - dst_y))


def compute_noc_proxy_metrics(
    packet_trace: pd.DataFrame,
    mesh_rows: int,
    mesh_cols: int,
) -> dict:
    if packet_trace.empty:
        return {
            "num_packets": 0,
            "num_spike_packets": 0,
            "num_relay_packets": 0,
            "average_hop": 0.0,
            "max_hop": 0,
            "total_hop": 0,
            "energy_proxy": 0.0,
            "hotspot_core": None,
            "hotspot_packet_count": 0,
        }

    hops: list[int] = []
    energy = 0.0
    hotspot_counts: Counter[int] = Counter()
    for row in packet_trace.to_dict(orient="records"):
        src_core = int(row["src_core"])
        dst_core = int(row["dst_core"])
        packet_size = float(row.get("packet_size", 1))
        hop = manhattan_hop(src_core, dst_core, mesh_cols)
        hops.append(hop)
        energy += packet_size * hop
        hotspot_counts[src_core] += 1
        hotspot_counts[dst_core] += 1

    hotspot_core, hotspot_count = min(
        hotspot_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )
    packet_types = packet_trace["packet_type"] if "packet_type" in packet_trace else []
    return {
        "num_packets": int(len(packet_trace)),
        "num_spike_packets": int(sum(1 for value in packet_types if value == "spike")),
        "num_relay_packets": int(sum(1 for value in packet_types if value == "relay")),
        "average_hop": float(sum(hops) / len(hops)),
        "max_hop": int(max(hops)),
        "total_hop": int(sum(hops)),
        "energy_proxy": float(energy),
        "hotspot_core": int(hotspot_core),
        "hotspot_packet_count": int(hotspot_count),
    }
