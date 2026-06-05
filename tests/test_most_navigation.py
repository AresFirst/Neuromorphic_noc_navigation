"""MoST 软件闭环导航演示测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from experiments.run_most_navigation import main as run_most_navigation_main
from graph.complex_graph_generator import generate_complex_graph
from graph.graph_io import save_graph_json
from loihi_planner.backend_check import check_brian2loihi_available


def test_run_most_navigation_with_prebuilt_graph(tmp_path, monkeypatch):
    status = check_brian2loihi_available()
    if not status["available"]:
        pytest.skip(f"Brian2Loihi unavailable: {status['error']}")

    graph = generate_complex_graph("community", 8, seed=2)
    graph_path = tmp_path / "graph.json"
    save_graph_json(graph, str(graph_path))

    output_dir = tmp_path / "navigation"
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_most_navigation.py",
            "--config",
            "configs/most.yaml",
            "--loihi-config",
            "configs/brian2loihi.yaml",
            "--graph",
            str(graph_path),
            "--output",
            str(output_dir),
            "--num-pairs",
            "1",
            "--seed",
            "0",
        ],
    )

    assert run_most_navigation_main() == 0

    summary_path = output_dir / "summary.json"
    graph_json = output_dir / "graph.json"
    results_csv = output_dir / "navigation_results.csv"
    preview_png = output_dir / "navigation_path_compare.png"

    assert summary_path.exists()
    assert graph_json.exists()
    assert results_csv.exists()
    assert preview_png.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["num_pairs"] == 1
    assert summary["success_rate"] == 1.0
    assert summary["navigation_path_compare_png"] == str(preview_png)
