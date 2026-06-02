"""MoST 文件查找与原始图加载测试。"""

from __future__ import annotations

from pathlib import Path

from dataset_import.most_importer import find_most_netxml, load_most_as_raw_graph


MOCK_NETXML = """<net>
    <junction id="A" x="0.0" y="0.0" type="priority"/>
    <junction id="B" x="10.0" y="0.0" type="priority"/>
    <junction id="C" x="20.0" y="0.0" type="priority"/>
    <edge id="most_edge_0" from="A" to="B">
        <lane id="most_edge_0_0" index="0" speed="10.0" length="10.0"/>
    </edge>
    <edge id="most_edge_1" from="B" to="C">
        <lane id="most_edge_1_0" index="0" speed="13.9" length="10.0"/>
    </edge>
    <edge id="most_edge_2" from="C" to="A">
        <lane id="most_edge_2_0" index="0" speed="13.9" length="20.0"/>
    </edge>
</net>
"""


def _write_mock(path: Path, size_padding: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = MOCK_NETXML + (" " * size_padding)
    path.write_text(content, encoding="utf-8")
    return path


def test_find_most_netxml_prefers_scenario_and_name_and_size(tmp_path):
    root = tmp_path / "MoSTScenario"
    _write_mock(root / "scenario" / "a" / "plain.net.xml", size_padding=5)
    _write_mock(root / "scenario" / "b" / "most_small.net.xml", size_padding=1)
    candidate_large = _write_mock(root / "scenario" / "c" / "monaco_large.net.xml", size_padding=20)
    _write_mock(root / "other" / "root_only.net.xml", size_padding=200)

    found = find_most_netxml(root)
    assert found == candidate_large

    raw_graph = load_most_as_raw_graph(root, found)
    assert raw_graph.graph["dataset_name"] == "MoST"
    assert raw_graph.graph["dataset_type"] == "sumo_netxml"
    assert raw_graph.graph["netxml_path"] == str(found)
