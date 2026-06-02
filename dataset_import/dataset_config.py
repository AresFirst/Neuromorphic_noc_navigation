"""公开道路数据集配置读取与校验。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def _require_mapping(data: Any, name: str) -> dict:
    if not isinstance(data, dict):
        raise ValueError(f"{name} must be a mapping")
    return data


def _require_keys(data: dict, keys: list[str], section: str) -> None:
    missing = [key for key in keys if key not in data]
    if missing:
        raise ValueError(f"{section} missing required field(s): {', '.join(missing)}")


def _resolve_path(value: Any, config_dir: Path, *, for_output: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"path value must be a string or null, got {type(value).__name__}")
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)

    config_relative = config_dir / path
    repo_relative = REPO_ROOT / path
    if for_output:
        return str(repo_relative)
    if config_relative.exists():
        return str(config_relative)
    return str(repo_relative)


def load_dataset_config(config_path: str) -> dict:
    """读取并校验公开道路数据集配置。

    相对输入路径按项目根目录解析；若配置文件旁边已经存在对应数据路径，
    则优先使用配置文件所在目录的相对路径，便于测试中使用临时目录。

    Args:
        config_path: YAML 配置文件路径。

    Returns:
        校验并解析过路径的普通 dict。

    Raises:
        ValueError: 配置格式或必要字段不合法。
    """
    path = Path(config_path).expanduser()
    if not path.is_absolute():
        cwd_candidate = Path.cwd() / path
        repo_candidate = REPO_ROOT / path
        if cwd_candidate.exists():
            path = cwd_candidate
        elif repo_candidate.exists():
            path = repo_candidate
        else:
            path = cwd_candidate
    if not path.exists():
        raise ValueError(f"dataset config not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    config = _require_mapping(raw, "dataset config")
    _require_keys(config, ["map_source", "dataset", "import", "output"], "dataset config")

    dataset = _require_mapping(config["dataset"], "dataset")
    import_config = _require_mapping(config["import"], "import")
    output = _require_mapping(config["output"], "output")

    _require_keys(dataset, ["name", "type", "root_dir", "path"], "dataset")
    _require_keys(
        import_config,
        [
            "auto_find_netxml",
            "ignore_internal_edges",
            "largest_strongly_connected_component",
            "simplify_graph",
            "max_nodes",
            "min_delay_ms",
            "max_delay_ms",
            "use_travel_time_if_speed_available",
            "region_method",
            "region_grid_rows",
            "region_grid_cols",
            "seed",
        ],
        "import",
    )
    _require_keys(
        output,
        ["output_dir", "graph_json", "graph_metrics_json", "preview_png", "import_summary_json"],
        "output",
    )

    if config["map_source"] != "dataset":
        raise ValueError("map_source must be 'dataset' for public road dataset imports")
    if int(import_config["min_delay_ms"]) < 1:
        raise ValueError("import.min_delay_ms must be positive")
    if int(import_config["max_delay_ms"]) < int(import_config["min_delay_ms"]):
        raise ValueError("import.max_delay_ms must be >= import.min_delay_ms")
    max_nodes = import_config.get("max_nodes")
    if max_nodes is not None and int(max_nodes) < 2:
        raise ValueError("import.max_nodes must be >= 2 or null")
    if int(import_config["region_grid_rows"]) < 1 or int(import_config["region_grid_cols"]) < 1:
        raise ValueError("region grid dimensions must be positive")

    config = dict(config)
    config["dataset"] = dict(dataset)
    config["import"] = dict(import_config)
    config["output"] = dict(output)

    config_dir = path.parent
    config["dataset"]["root_dir"] = _resolve_path(dataset["root_dir"], config_dir)
    config["dataset"]["path"] = _resolve_path(dataset["path"], config_dir)
    for key in ["output_dir", "graph_json", "graph_metrics_json", "preview_png", "import_summary_json"]:
        config["output"][key] = _resolve_path(output[key], config_dir, for_output=True)

    return config
