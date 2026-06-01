"""Loihi 运行时配置加载。

提供 SNN 模拟器参数的 YAML 加载和规范化。
Brian2LoihiRuntimeConfig 是 frozen dataclass，
确保配置对象在创建后不可变，防止实验中意外修改参数。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Brian2LoihiRuntimeConfig:
    """Brian2Loihi SNN 运行时配置（frozen dataclass，创建后不可修改）。

    Attributes:
        backend: 后端选择，固定为 "brian2loihi"。
        dt_ms: 离散时间步长 (毫秒)。对应 Loihi 的整数 time step。
        threshold: 神经元发放阈值。v > threshold 时发放脉冲。
        weight: 突触权重。必须 > threshold 以保证单次脉冲触发传播。
        refractory_ms: 不应期 (毫秒)。设为大值 (~1000) 保证每个神经元只发放一次。
        seed: 随机种子。
    """
    backend: str = "brian2loihi"
    dt_ms: int = 1
    threshold: float = 1.0
    weight: float = 1.1
    refractory_ms: int = 1000
    seed: int = 0


def load_brian2loihi_config(path: str | Path) -> dict[str, Any]:
    """从 YAML 文件加载配置并返回规范化后的字典。

    Args:
        path: YAML 配置文件路径 (如 configs/brian2loihi.yaml)。

    Returns:
        配置字典 (via asdict)，包含所有字段及其默认值。
        缺失字段使用 Brian2LoihiRuntimeConfig 的默认值。
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    config = Brian2LoihiRuntimeConfig(
        backend=str(data.get("backend", "brian2loihi")),
        dt_ms=int(data.get("dt_ms", 1)),
        threshold=float(data.get("threshold", 1.0)),
        weight=float(data.get("weight", 1.1)),
        refractory_ms=int(data.get("refractory_ms", 1000)),
        seed=int(data.get("seed", 0)),
    )
    return asdict(config)


def normalize_wavefront_config(data: dict[str, Any] | None) -> dict[str, Any]:
    """从原始字典规范化配置（非文件方式，用于编程式调用）。

    Args:
        data: 配置字典或 None。

    Returns:
        规范化后的配置字典，缺失字段自动填充默认值。
    """
    payload = data or {}
    return asdict(
        Brian2LoihiRuntimeConfig(
            backend=str(payload.get("backend", "brian2loihi")),
            dt_ms=int(payload.get("dt_ms", 1)),
            threshold=float(payload.get("threshold", 1.0)),
            weight=float(payload.get("weight", 1.1)),
            refractory_ms=int(payload.get("refractory_ms", 1000)),
            seed=int(payload.get("seed", 0)),
        )
    )
