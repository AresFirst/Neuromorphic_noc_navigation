"""配置加载辅助函数。"""

from __future__ import annotations

from pathlib import Path

import yaml


def load_yaml_config(path: str | Path) -> dict:
    config_path = Path(path).expanduser()
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
