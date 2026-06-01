import pandas as pd

from noc.noc_proxy_metrics import compute_noc_proxy_metrics, manhattan_hop


def test_manhattan_hop_computes_mesh_distance():
    assert manhattan_hop(0, 10, mesh_cols=4) == 4
    assert manhattan_hop(5, 5, mesh_cols=4) == 0


def test_proxy_metrics_empty_trace_does_not_crash():
    metrics = compute_noc_proxy_metrics(pd.DataFrame(), mesh_rows=4, mesh_cols=4)
    assert metrics["num_packets"] == 0
    assert metrics["average_hop"] == 0.0
    assert metrics["hotspot_core"] is None
