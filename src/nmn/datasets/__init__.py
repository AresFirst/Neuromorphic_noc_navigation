"""公开道路数据集导入的标准入口。"""

from __future__ import annotations

import sys
from importlib import import_module

from dataset_import.dataset_config import load_dataset_config
from dataset_import.dataset_loader import load_public_road_dataset_as_graph
from dataset_import.most_importer import find_most_netxml, load_most_as_raw_graph
from dataset_import.road_graph_normalizer import normalize_road_graph
from dataset_import.sumo_netxml_importer import load_sumo_netxml_as_graph

_ALIASES = {
    "config": "dataset_import.dataset_config",
    "loader": "dataset_import.dataset_loader",
    "most": "dataset_import.most_importer",
    "normalizer": "dataset_import.road_graph_normalizer",
    "sumo_netxml": "dataset_import.sumo_netxml_importer",
}

for name, module_name in _ALIASES.items():
    sys.modules[f"{__name__}.{name}"] = import_module(module_name)

__all__ = [
    "find_most_netxml",
    "load_dataset_config",
    "load_most_as_raw_graph",
    "load_public_road_dataset_as_graph",
    "load_sumo_netxml_as_graph",
    "normalize_road_graph",
]
