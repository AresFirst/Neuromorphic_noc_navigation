"""流量表生成: 数据包跟踪 → Noxim 兼容的流量文件。

Noxim 支持两种流量注入格式:

1. hardcoded 格式 (逐周期指定):
   每个周期列出该周期注入的所有 (src_core, dst_core) 对
   周期之间以 "-1 -1" 分隔
   适用场景: 精确的重放 (replay) 已记录的通信模式

2. traffic table 格式 (统计聚合):
   每行 = (src, dst, count, total_size, injection_rate)
   Noxim 根据统计信息自行生成注入时间
   适用场景: 统计性流量模式

本模块提供从 packet_trace DataFrame 到两种格式的转换。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def save_sample_noxim_traffic_table(path: str) -> None:
    """生成一个最小的样例 Noxim 流量表文件（用于测试）。

    包含 3 条沿对角线的流量记录。

    Args:
        path: 输出文件路径。
    """
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# src_x src_y dst_x dst_y packet_size injection_time",
        "0 0 1 1 8 0",   # core(0,0) → core(1,1) @ t=0
        "1 1 2 2 8 4",   # core(1,1) → core(2,2) @ t=4
        "2 2 3 3 8 8",   # core(2,2) → core(3,3) @ t=8
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def packet_trace_to_traffic_table(
    packet_trace: pd.DataFrame,
    num_cores: int,
) -> pd.DataFrame:
    """将包跟踪聚合为 Noxim traffic table 格式的 DataFrame。

    按 (src_core, dst_core) 分组，统计:
    - packet_count: 该 (src,dst) 对的包总数
    - total_packet_size: 总 flits 数
    - injection_rate: 该流占总包数的比例

    Args:
        packet_trace: 包跟踪 DataFrame (PACKET_COLUMNS 格式)。
        num_cores: core 总数（仅用于验证，当前未使用）。

    Returns:
        DataFrame，列: [src_core, dst_core, packet_count, total_packet_size, injection_rate]。
    """
    if num_cores <= 0:
        raise ValueError("num_cores must be positive")

    columns = ["src_core", "dst_core", "packet_count", "total_packet_size", "injection_rate"]
    if packet_trace.empty:
        return pd.DataFrame(columns=columns)

    # 按 (src_core, dst_core) 分组聚合
    grouped = (
        packet_trace.groupby(["src_core", "dst_core"], as_index=False)
        .agg(packet_count=("packet_size", "count"), total_packet_size=("packet_size", "sum"))
        .sort_values(["src_core", "dst_core"], ignore_index=True)
    )
    total_packets = float(grouped["packet_count"].sum())
    # injection_rate = 此流包数 / 总包数 (归一化注入概率)
    grouped["injection_rate"] = grouped["packet_count"].astype(float) / total_packets if total_packets else 0.0
    return grouped[columns]


def packet_trace_to_hardcoded_traffic_lines(
    packet_trace: pd.DataFrame,
    cycle_column: str = "cycle",
) -> list[str]:
    """将包跟踪转换为 Noxim hardcoded 流量格式的文本行。

    格式:
        # Noxim hardcoded traffic ...
        # src_core dst_core
        <src> <dst>         # cycle=0 的包
        ...
        -1 -1               # cycle=0 结束
        <src> <dst>         # cycle=1 的包
        ...
        -1 -1               # cycle=1 结束

    Args:
        packet_trace: 包跟踪 DataFrame。
        cycle_column: 周期的列名。

    Returns:
        文本行列表（含注释头和 -1 -1 分隔符）。

    Raises:
        ValueError: DataFrame 缺少必需列。
    """
    lines = [
        "# Noxim hardcoded traffic generated from spike packet traces",
        "# src_core dst_core",
    ]
    if packet_trace.empty:
        lines.append("-1 -1")
        return lines

    # 验证必需列
    required_columns = {"src_core", "dst_core", cycle_column}
    missing = required_columns.difference(packet_trace.columns)
    if missing:
        raise ValueError(f"packet_trace is missing required columns: {sorted(missing)}")

    # 逐周期生成注入指令
    max_cycle = int(packet_trace[cycle_column].max())
    for cycle in range(max_cycle + 1):
        # 当前周期的所有包
        cycle_rows = packet_trace[packet_trace[cycle_column] == cycle]
        for row in cycle_rows.sort_values(["src_core", "dst_core"]).to_dict(orient="records"):
            lines.append(f"{int(row['src_core'])} {int(row['dst_core'])}")
        # 周期结束标记
        lines.append("-1 -1")
    return lines


def save_noxim_hardcoded_traffic(
    packet_trace: pd.DataFrame,
    path: str,
    cycle_column: str = "cycle",
) -> None:
    """保存 hardcoded 流量文件到磁盘。

    Args:
        packet_trace: 包跟踪 DataFrame。
        path: 输出文件路径。
        cycle_column: 周期列名。
    """
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = packet_trace_to_hardcoded_traffic_lines(packet_trace, cycle_column=cycle_column)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_noxim_traffic_table(
    traffic_table: pd.DataFrame,
    path: str,
) -> None:
    """保存 traffic table 文件到磁盘。

    Args:
        traffic_table: 聚合流量表 DataFrame。
        path: 输出文件路径。
    """
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
