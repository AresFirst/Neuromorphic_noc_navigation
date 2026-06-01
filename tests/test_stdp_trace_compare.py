import math

from graph.complex_graph_generator import generate_complex_graph
from graph.graph_baseline import dijkstra_delay_path, sample_start_target_pairs
from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from loihi_planner.path_compare import compare_snn_path_with_dijkstra
from loihi_planner.path_reconstruction import reconstruct_path_from_parent
from loihi_planner.stdp_trace import build_stdp_trace_table
from loihi_planner.wavefront_reference import event_driven_wavefront
from tests.test_wavefront_reference import _build_small_wavefront_graph


def test_stdp_trace_weights_mark_parent_edges():
    graph = _build_small_wavefront_graph()
    spike_times = {0: 0.0, 1: 1.0, 2: 3.0, 3: 2.0, 4: 3.0}
    parent_trace = infer_parent_trace_from_spikes(graph, spike_times, start=0)
    stdp_df = build_stdp_trace_table(graph, parent_trace, spike_times)

    parent_row = stdp_df[(stdp_df["pre"] == 3) & (stdp_df["post"] == 4)].iloc[0]
    non_parent_row = stdp_df[(stdp_df["pre"] == 2) & (stdp_df["post"] == 3)].iloc[0]
    assert parent_row["stdp_weight"] == 1.0
    assert non_parent_row["stdp_weight"] == 0.0


def test_snn_path_matches_dijkstra_on_30_node_complex_graph():
    graph = generate_complex_graph("community", 30, seed=9)
    pairs = sample_start_target_pairs(graph, 10, seed=4)

    ratios = []
    for start, target in pairs:
        reference = event_driven_wavefront(graph, start, target, delay_attr="delay_ms")
        parent_trace = infer_parent_trace_from_spikes(graph, reference["arrival_times"], start, delay_attr="delay_ms")
        snn_path = reconstruct_path_from_parent(parent_trace, start, target)
        dijkstra_path, _ = dijkstra_delay_path(graph, start, target, delay_attr="delay_ms")
        compare = compare_snn_path_with_dijkstra(graph, snn_path, dijkstra_path, weight="delay_ms")
        assert compare["same_cost"]
        assert math.isclose(compare["optimality_ratio"], 1.0, rel_tol=1e-9, abs_tol=1e-9)
        ratios.append(compare["optimality_ratio"])

    assert len(ratios) == 10
