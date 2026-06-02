"""MoST 导入 CLI 端到端测试。"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.run_most_import import main as run_most_import_main
from graph.graph_io import load_graph_json


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

    output_dir = tmp_path / "results"
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
  output_dir: {str(output_dir)}
  graph_json: {str(output_dir / "graph.json")}
  graph_metrics_json: {str(output_dir / "graph_metrics.json")}
  preview_png: {str(output_dir / "preview.png")}
  import_summary_json: {str(output_dir / "import_summary.json")}
""",
        encoding="utf-8",
    )
    return config


def test_run_most_import_cli(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    monkeypatch.setattr("sys.argv", ["run_most_import.py", "--config", str(config_path)])

    exit_code = run_most_import_main()
    assert exit_code == 0

    output_dir = tmp_path / "results"
    graph_json = output_dir / "graph.json"
    summary_json = output_dir / "import_summary.json"
    preview_png = output_dir / "preview.png"
    metrics_json = output_dir / "graph_metrics.json"

    assert graph_json.exists()
    assert summary_json.exists()
    assert preview_png.exists()
    assert metrics_json.exists()

    graph = load_graph_json(str(graph_json))
    assert graph.graph["dataset_name"] == "MoST"
    assert graph.graph["normalized"] is True
    assert graph.number_of_nodes() == 3
    assert graph.number_of_edges() == 3

    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary["dataset_name"] == "MoST"
    assert summary["num_nodes"] == 3
    assert summary["num_edges"] == 3
    assert summary["output_graph_json"] == str(graph_json)
