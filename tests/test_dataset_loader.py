"""公开道路数据集加载入口测试。"""

from __future__ import annotations

from pathlib import Path

from dataset_import.dataset_loader import load_public_road_dataset_as_graph


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


def _write_config(tmp_path: Path) -> Path:
    dataset_root = tmp_path / "dataset"
    netxml_path = dataset_root / "scenario" / "in" / "most.net.xml"
    netxml_path.parent.mkdir(parents=True, exist_ok=True)
    netxml_path.write_text(MOCK_NETXML, encoding="utf-8")

    config = tmp_path / "most.yaml"
    config.write_text(
        f"""map_source: dataset
dataset:
  name: MoST
  type: sumo_netxml
  root_dir: dataset
  path: null
import:
  auto_find_netxml: true
  ignore_internal_edges: true
  largest_strongly_connected_component: true
  simplify_graph: true
  max_nodes: 2000
  min_delay_ms: 1
  max_delay_ms: 10
  use_travel_time_if_speed_available: true
  region_method: spatial_grid
  region_grid_rows: 4
  region_grid_cols: 4
  seed: 0
output:
  output_dir: {str(tmp_path / "results")}
  graph_json: {str(tmp_path / "results" / "graph.json")}
  graph_metrics_json: {str(tmp_path / "results" / "graph_metrics.json")}
  preview_png: {str(tmp_path / "results" / "preview.png")}
  import_summary_json: {str(tmp_path / "results" / "import_summary.json")}
""",
        encoding="utf-8",
    )
    return config


def test_load_public_road_dataset_as_graph(tmp_path):
    config_path = _write_config(tmp_path)
    graph = load_public_road_dataset_as_graph(str(config_path))

    assert graph.graph["dataset_name"] == "MoST"
    assert graph.graph["normalized"] is True
    assert graph.number_of_nodes() == 3
    assert graph.number_of_edges() == 3
    for _, attrs in graph.nodes(data=True):
        assert attrs["source"] == "most"
        assert isinstance(attrs["region"], int)
