"""新包结构冒烟测试。"""

from __future__ import annotations

from nmn.datasets.loader import load_public_road_dataset_as_graph
from nmn.graph.synthetic import generate_complex_graph
from nmn.loihi.backend import check_brian2loihi_available
from nmn.noc.proxy_metrics import manhattan_hop


def test_nmn_package_imports_are_available():
    graph = generate_complex_graph("community", 5, seed=0)

    assert graph.number_of_nodes() == 5
    assert callable(load_public_road_dataset_as_graph)
    assert callable(check_brian2loihi_available)
    assert manhattan_hop(0, 3, mesh_cols=2) == 2
