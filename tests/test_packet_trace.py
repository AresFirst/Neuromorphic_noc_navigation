from noc.mapping import create_core_mapping
from noc.packet_trace import relay_events_to_packet_trace, spike_trace_to_packet_trace
from tests.test_wavefront_reference import _build_small_wavefront_graph


def test_packet_trace_contains_required_columns():
    graph = _build_small_wavefront_graph()
    mapping = create_core_mapping(graph, 2, 3, "topology", seed=0)
    spike_times = {0: 0.0, 1: 1.0, 2: 3.0, 3: 2.0, 4: 3.0}
    packet_trace = spike_trace_to_packet_trace(graph, spike_times, mapping)

    assert list(packet_trace.columns) == [
        "cycle",
        "src_neuron",
        "dst_neuron",
        "src_core",
        "dst_core",
        "packet_type",
        "packet_size",
    ]
    assert len(packet_trace) >= 3
    assert set(packet_trace["packet_type"]) == {"spike"}


def test_relay_events_to_packet_trace_generates_control_packets():
    mapping = {0: 0, 1: 1}
    packet_trace = relay_events_to_packet_trace(
        [{"cycle": 5, "edge_u": 0, "edge_v": 1, "event_type": "blocked"}],
        mapping,
        relay_core=0,
    )
    assert len(packet_trace) == 2
    assert set(packet_trace["packet_type"]) == {"relay"}
