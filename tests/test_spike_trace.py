from loihi_planner.spike_trace import load_spike_trace, save_spike_trace, spike_trace_to_dataframe


def test_spike_trace_dataframe_and_roundtrip(tmp_path):
    spike_times = {3: 2.0, 0: 0.0, 4: 3.0}
    df = spike_trace_to_dataframe(spike_times)

    assert list(df.columns) == ["neuron_id", "spike_time_ms"]
    assert df.iloc[0]["neuron_id"] == 0
    assert df.iloc[1]["neuron_id"] == 3
    assert df.iloc[2]["neuron_id"] == 4

    path = tmp_path / "spikes.csv"
    save_spike_trace(spike_times, str(path))
    loaded = load_spike_trace(str(path))
    assert list(loaded.columns) == ["neuron_id", "spike_time_ms"]
    assert loaded.to_dict(orient="list") == df.to_dict(orient="list")
