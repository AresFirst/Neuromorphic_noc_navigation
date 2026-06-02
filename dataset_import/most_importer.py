"""MoST / Monaco SUMO Traffic Scenario 导入辅助函数。"""

from __future__ import annotations

from pathlib import Path

import networkx as nx

from .sumo_netxml_importer import load_sumo_netxml_as_graph


_EXCLUDED_NAME_PARTS = ("plain", "edg", "nod", "typ")
_PREFERRED_NAME_PARTS = ("most", "monaco")


def _filtered_netxml_files(search_root: Path) -> list[Path]:
    if not search_root.exists():
        return []
    files = []
    for path in search_root.rglob("*.net.xml"):
        name = path.name.lower()
        if any(part in name for part in _EXCLUDED_NAME_PARTS):
            continue
        files.append(path)
    return files


def _select_best_candidate(candidates: list[Path]) -> Path:
    preferred = [
        path for path in candidates
        if any(part in path.name.lower() for part in _PREFERRED_NAME_PARTS)
    ]
    pool = preferred or candidates
    return max(pool, key=lambda path: path.stat().st_size)


def find_most_netxml(root_dir: str | Path) -> Path:
    """在 MoSTScenario 本地目录中自动查找主 `.net.xml` 文件。

    查找顺序:
    1. `root_dir/scenario` 下递归查找；
    2. 若未找到，再在 `root_dir` 下递归查找；
    3. 排除 plain/edg/nod/typ 等中间网络文件；
    4. 优先选择文件名包含 most 或 monaco 的文件；
    5. 仍有多个时选择文件大小最大的文件。
    """
    root = Path(root_dir).expanduser()
    scenario_candidates = _filtered_netxml_files(root / "scenario")
    candidates = scenario_candidates or _filtered_netxml_files(root)
    if not candidates:
        raise FileNotFoundError(
            "MoST .net.xml not found. Please download MoSTScenario first, for example: "
            "git clone https://github.com/lcodeca/MoSTScenario.git data/datasets/MoSTScenario"
        )
    return _select_best_candidate(candidates)


def load_most_as_raw_graph(
    root_dir: str | Path,
    netxml_path: str | Path | None = None,
    ignore_internal_edges: bool = True,
    use_travel_time_if_speed_available: bool = True,
) -> nx.DiGraph:
    """加载 MoST `.net.xml` 并返回未标准化的道路图。"""
    path = Path(netxml_path).expanduser() if netxml_path is not None else find_most_netxml(root_dir)
    graph = load_sumo_netxml_as_graph(
        str(path),
        ignore_internal_edges=ignore_internal_edges,
        use_travel_time_if_speed_available=use_travel_time_if_speed_available,
    )
    graph.graph.update(
        {
            "dataset_name": "MoST",
            "dataset_type": "sumo_netxml",
            "netxml_path": str(path),
        }
    )
    return graph
