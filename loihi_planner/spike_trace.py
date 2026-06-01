from __future__ import annotations

from pathlib import Path

import pandas as pd


def spike_trace_to_dataframe(spike_times_by_neuron: dict) -> pd.DataFrame:
    rows = [
        {"neuron_id": int(neuron_id), "spike_time_ms": float(spike_time)}
        for neuron_id, spike_time in sorted(
            spike_times_by_neuron.items(), key=lambda item: (float(item[1]), int(item[0]))
        )
    ]
    return pd.DataFrame(rows, columns=["neuron_id", "spike_time_ms"])


def save_spike_trace(spike_times_by_neuron: dict, path: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    spike_trace_to_dataframe(spike_times_by_neuron).to_csv(output, index=False)


def load_spike_trace(path: str) -> pd.DataFrame:
    return pd.read_csv(path)
