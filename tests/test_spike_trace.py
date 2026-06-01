"""测试脉冲记录 CSV 读写。

验证 spike_trace_to_dataframe / save_spike_trace / load_spike_trace:
- DataFrame 按时间排序
- CSV 往返后数据一致
"""

from loihi_planner.spike_trace import load_spike_trace, save_spike_trace, spike_trace_to_dataframe


def test_spike_trace_dataframe_and_roundtrip(tmp_path):
    """验证脉冲数据: DataFrame 排序正确，CSV 往返一致。

    输入脉冲: {3: 2.0, 0: 0.0, 4: 3.0}
    预期排序: neuron 0 (t=0) → 3 (t=2) → 4 (t=3)
    """
    spike_times = {3: 2.0, 0: 0.0, 4: 3.0}
    df = spike_trace_to_dataframe(spike_times)

    # 验证按时间升序排列
    assert list(df.columns) == ["neuron_id", "spike_time_ms"]
    assert df.iloc[0]["neuron_id"] == 0   # 最早发放
    assert df.iloc[1]["neuron_id"] == 3
    assert df.iloc[2]["neuron_id"] == 4   # 最晚发放

    # CSV 往返测试
    path = tmp_path / "spikes.csv"
    save_spike_trace(spike_times, str(path))
    loaded = load_spike_trace(str(path))
    assert list(loaded.columns) == ["neuron_id", "spike_time_ms"]
    assert loaded.to_dict(orient="list") == df.to_dict(orient="list")
