"""SUMO `.net.xml` 导入测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dataset_import.sumo_netxml_importer import load_sumo_netxml_as_graph


MOCK_NETXML = """<net>
    <junction id="A" x="0.0" y="0.0" type="priority"/>
    <junction id="B" x="10.0" y="0.0" type="priority"/>
    <junction id="C" x="20.0" y="0.0" type="priority"/>
    <edge id="most_edge_0" from="A" to="B">
        <lane id="most_edge_0_0" index="0" speed="10.0" length="10.0"/>
        <lane id="most_edge_0_1" index="1" speed="20.0" length="20.0"/>
    </edge>
    <edge id="most_edge_0_dup" from="A" to="B">
        <lane id="most_edge_0_dup_0" index="0" speed="1.0" length="100.0"/>
    </edge>
    <edge id="most_edge_1" from="B" to="C">
        <lane id="most_edge_1_0" index="0" speed="13.9" length="10.0"/>
    </edge>
    <edge id="most_edge_2" from="C" to="A">
        <lane id="most_edge_2_0" index="0" speed="13.9" length="20.0"/>
    </edge>
    <edge id=":internal" from="B" to="B">
        <lane id=":internal_0" index="0" speed="13.9" length="1.0"/>
    </edge>
</net>
"""


def _write_mock_netxml(tmp_path: Path) -> Path:
    path = tmp_path / "mock.net.xml"
    path.write_text(MOCK_NETXML, encoding="utf-8")
    return path


def test_sumo_netxml_importer_parses_junctions_lanes_and_ignores_internal_edges(tmp_path):
    path = _write_mock_netxml(tmp_path)
    graph = load_sumo_netxml_as_graph(str(path))

    assert set(graph.nodes()) == {"A", "B", "C"}
    assert graph.number_of_edges() == 3
    assert not graph.has_edge("B", "B")

    edge = graph["A"]["B"]
    assert edge["distance"] == pytest.approx(15.0)
    assert edge["speed"] == pytest.approx(15.0)
    assert edge["base_cost"] == pytest.approx(1.0)
    assert edge["num_lanes"] == 2
    assert edge["source"] == "most_raw"
    assert edge["original_edge_id"] == "most_edge_0"
    assert edge["merged_edge_ids"] == ["most_edge_0", "most_edge_0_dup"]

    edge_bc = graph["B"]["C"]
    assert edge_bc["distance"] == pytest.approx(10.0)
    assert edge_bc["speed"] == pytest.approx(13.9)
    assert edge_bc["base_cost"] == pytest.approx(10.0 / 13.9)

    edge_ca = graph["C"]["A"]
    assert edge_ca["distance"] == pytest.approx(20.0)
    assert edge_ca["base_cost"] == pytest.approx(20.0 / 13.9)
