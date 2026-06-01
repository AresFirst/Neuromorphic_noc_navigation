"""脉冲记录数据的 CSV 读写。

提供 SNN 仿真产生的脉冲时间序列数据与 pandas DataFrame / CSV 文件的转换。

数据格式:
    DataFrame 列: ["neuron_id", "spike_time_ms"]
    每条记录表示: 神经元 neuron_id 在 spike_time_ms 时刻首次发放脉冲
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def spike_trace_to_dataframe(spike_times_by_neuron: dict) -> pd.DataFrame:
    """将脉冲时间字典转换为 DataFrame。

    Args:
        spike_times_by_neuron: {神经元ID: 首次发放时间(ms)} 字典。

    Returns:
        DataFrame，列=["neuron_id", "spike_time_ms"]，
        按发放时间升序排列（时间相同时按神经元 ID 升序）。
    """
    rows = [
        {"neuron_id": int(neuron_id), "spike_time_ms": float(spike_time)}
        for neuron_id, spike_time in sorted(
            # 先按时间排序，再按神经元 ID 排序（tie-breaker）
            spike_times_by_neuron.items(), key=lambda item: (float(item[1]), int(item[0]))
        )
    ]
    return pd.DataFrame(rows, columns=["neuron_id", "spike_time_ms"])


def save_spike_trace(spike_times_by_neuron: dict, path: str) -> None:
    """将脉冲时间字典保存为 CSV 文件。

    Args:
        spike_times_by_neuron: {神经元ID: 首次发放时间(ms)} 字典。
        path: 输出 CSV 文件路径（自动创建父目录）。
    """
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    spike_trace_to_dataframe(spike_times_by_neuron).to_csv(output, index=False)


def load_spike_trace(path: str) -> pd.DataFrame:
    """从 CSV 文件加载脉冲数据。

    Args:
        path: CSV 文件路径。

    Returns:
        DataFrame，列=["neuron_id", "spike_time_ms"]。
    """
    return pd.read_csv(path)
