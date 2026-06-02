"""公开道路数据集统一加载入口。"""

from __future__ import annotations

from pathlib import Path

import networkx as nx

from .dataset_config import REPO_ROOT, load_dataset_config
from .most_importer import load_most_as_raw_graph
from .road_graph_normalizer import normalize_road_graph


def _fallback_root_dir(root_dir: str) -> str:
    root = Path(root_dir).expanduser()
    if root.exists():
        return str(root)

    for relative in [
        "datasets/MoSTScenario",
        "datasets/MoSTScenario-master",
        "data/datasets/MoSTScenario",
        "data/datasets/MoSTScenario-master",
    ]:
        candidate = REPO_ROOT / relative
        if candidate.exists():
            return str(candidate)
    return str(root)


def load_public_road_dataset_as_graph(config_path: str) -> nx.DiGraph:
    """从配置文件加载公开道路数据集并返回标准化 DiGraph。

    当前只实现 MoST / SUMO `.net.xml`。其他数据集类型会明确抛出
    NotImplementedError，避免静默回退到 synthetic graph。
    """
    config = load_dataset_config(config_path)
    dataset = config["dataset"]
    import_config = config["import"]

    dataset_name = str(dataset.get("name", ""))
    dataset_type = str(dataset.get("type", ""))
    if dataset_name != "MoST" or dataset_type != "sumo_netxml":
        raise NotImplementedError("current importer only supports MoST with type=sumo_netxml")

    netxml_path = dataset.get("path")
    if not netxml_path and not bool(import_config.get("auto_find_netxml", True)):
        raise ValueError("dataset.path must be set when import.auto_find_netxml is false")

    raw_graph = load_most_as_raw_graph(
        root_dir=_fallback_root_dir(dataset["root_dir"]),
        netxml_path=netxml_path,
        ignore_internal_edges=bool(import_config.get("ignore_internal_edges", True)),
        use_travel_time_if_speed_available=bool(
            import_config.get("use_travel_time_if_speed_available", True)
        ),
    )
    return normalize_road_graph(
        raw_graph,
        min_delay_ms=int(import_config.get("min_delay_ms", 1)),
        max_delay_ms=int(import_config.get("max_delay_ms", 10)),
        largest_strongly_connected_component=bool(
            import_config.get("largest_strongly_connected_component", True)
        ),
        max_nodes=(
            None if import_config.get("max_nodes") is None else int(import_config.get("max_nodes"))
        ),
        region_method=str(import_config.get("region_method", "spatial_grid")),
        region_grid_rows=int(import_config.get("region_grid_rows", 4)),
        region_grid_cols=int(import_config.get("region_grid_cols", 4)),
        seed=int(import_config.get("seed", 0)),
        source="most",
    )
