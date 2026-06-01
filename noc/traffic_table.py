from __future__ import annotations

from pathlib import Path

import pandas as pd


def save_sample_noxim_traffic_table(path: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# src_x src_y dst_x dst_y packet_size injection_time",
        "0 0 1 1 8 0",
        "1 1 2 2 8 4",
        "2 2 3 3 8 8",
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def packet_trace_to_traffic_table(
    packet_trace: pd.DataFrame,
    num_cores: int,
) -> pd.DataFrame:
    if num_cores <= 0:
        raise ValueError("num_cores must be positive")

    columns = ["src_core", "dst_core", "packet_count", "total_packet_size", "injection_rate"]
    if packet_trace.empty:
        return pd.DataFrame(columns=columns)

    grouped = (
        packet_trace.groupby(["src_core", "dst_core"], as_index=False)
        .agg(packet_count=("packet_size", "count"), total_packet_size=("packet_size", "sum"))
        .sort_values(["src_core", "dst_core"], ignore_index=True)
    )
    total_packets = float(grouped["packet_count"].sum())
    grouped["injection_rate"] = grouped["packet_count"].astype(float) / total_packets if total_packets else 0.0
    return grouped[columns]


def packet_trace_to_hardcoded_traffic_lines(
    packet_trace: pd.DataFrame,
    cycle_column: str = "cycle",
) -> list[str]:
    lines = [
        "# Noxim hardcoded traffic generated from spike packet traces",
        "# src_core dst_core",
    ]
    if packet_trace.empty:
        lines.append("-1 -1")
        return lines

    required_columns = {"src_core", "dst_core", cycle_column}
    missing = required_columns.difference(packet_trace.columns)
    if missing:
        raise ValueError(f"packet_trace is missing required columns: {sorted(missing)}")

    max_cycle = int(packet_trace[cycle_column].max())
    for cycle in range(max_cycle + 1):
        cycle_rows = packet_trace[packet_trace[cycle_column] == cycle]
        for row in cycle_rows.sort_values(["src_core", "dst_core"]).to_dict(orient="records"):
            lines.append(f"{int(row['src_core'])} {int(row['dst_core'])}")
        lines.append("-1 -1")
    return lines


def save_noxim_hardcoded_traffic(
    packet_trace: pd.DataFrame,
    path: str,
    cycle_column: str = "cycle",
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = packet_trace_to_hardcoded_traffic_lines(packet_trace, cycle_column=cycle_column)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_noxim_traffic_table(
    traffic_table: pd.DataFrame,
    path: str,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Approximate Noxim traffic table generated from spike packet traces",
        "# src_core dst_core packet_count total_packet_size injection_rate",
    ]
    for row in traffic_table.to_dict(orient="records"):
        lines.append(
            f"{int(row['src_core'])} {int(row['dst_core'])} "
            f"{int(row['packet_count'])} {int(row['total_packet_size'])} "
            f"{float(row['injection_rate']):.8f}"
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
