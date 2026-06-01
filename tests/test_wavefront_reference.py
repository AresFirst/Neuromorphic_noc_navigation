import networkx as nx

from loihi_planner.wavefront_reference import event_driven_wavefront


def _build_small_wavefront_graph() -> nx.DiGraph:
    G = nx.DiGraph()
    for node in range(5):
        G.add_node(node, x=float(node), y=float(node), region=0)
    edges = [
        (0, 1, 1),
        (0, 2, 3),
        (1, 3, 1),
        (2, 3, 1),
        (3, 4, 1),
    ]
    for source, target, delay in edges:
        G.add_edge(
            source,
            target,
            delay_ms=int(delay),
            base_cost=float(delay),
            original_delay_ms=int(delay),
            state="normal",
            distance=float(delay),
        )
    return G


def test_reference_wavefront_reaches_target_at_3_ms():
    graph = _build_small_wavefront_graph()
    result = event_driven_wavefront(graph, 0, 4)

    assert result["target_arrival_time"] == 3.0
    assert result["arrival_times"][0] == 0.0
    assert result["arrival_times"][4] == 3.0
    assert result["visited_order"][0] == 0


def test_reference_wavefront_skips_blocked_edges():
    graph = nx.DiGraph()
    for node in range(3):
        graph.add_node(node, x=float(node), y=float(node), region=0)
    graph.add_edge(0, 1, delay_ms=1, base_cost=1.0, original_delay_ms=1, state="blocked", distance=1.0)
    graph.add_edge(0, 2, delay_ms=2, base_cost=2.0, original_delay_ms=2, state="normal", distance=2.0)
    graph.add_edge(2, 1, delay_ms=1, base_cost=1.0, original_delay_ms=1, state="normal", distance=1.0)

    result = event_driven_wavefront(graph, 0, 1)
    assert result["target_arrival_time"] == 3.0
    assert result["arrival_times"][1] == 3.0
