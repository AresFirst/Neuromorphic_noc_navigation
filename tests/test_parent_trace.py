from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from tests.test_wavefront_reference import _build_small_wavefront_graph


def test_parent_trace_prefers_earliest_parent():
    graph = _build_small_wavefront_graph()
    spike_times = {0: 0.0, 1: 1.0, 2: 3.0, 3: 2.0, 4: 3.0}

    parent_trace = infer_parent_trace_from_spikes(graph, spike_times, start=0)
    assert parent_trace[0] is None
    assert parent_trace[1] == 0
    assert parent_trace[2] == 0
    assert parent_trace[3] == 1
    assert parent_trace[4] == 3
