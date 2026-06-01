import networkx as nx

from localization.dynamic_start import estimate_start_node_from_position
from localization.place_cells import PlaceCellLayer


def test_place_cell_winner_returns_node_at_own_coordinate():
    positions = {0: (0.0, 0.0), 1: (0.5, 0.5), 2: (1.0, 1.0)}
    layer = PlaceCellLayer(positions, sigma=0.1)
    assert layer.winner_take_all(0.5, 0.5) == 1


def test_estimate_start_node_from_position_returns_graph_node():
    graph = nx.DiGraph()
    graph.add_node(0, x=0.0, y=0.0, region=0)
    graph.add_node(1, x=1.0, y=1.0, region=1)
    assert estimate_start_node_from_position(graph, 0.9, 0.9) == 1
