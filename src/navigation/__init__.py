"""Navigation result models and SNN planner wrapper."""

from __future__ import annotations

# navigation 包是 GUI 调用 SNN 规划的主入口，隐藏 Loihi/CPU fallback 的细节。
from .benchmarks import AlgorithmBenchmarkResult, run_algorithm_benchmarks
from .incremental import run_incremental_snn_navigation
from .planner import run_navigation
from .result import NavigationResult, WavefrontFrame

# 对外结果结构固定为 NavigationResult/WavefrontFrame，便于 GUI 和测试统一消费。
__all__ = [
    "AlgorithmBenchmarkResult",
    "NavigationResult",
    "WavefrontFrame",
    "run_algorithm_benchmarks",
    "run_incremental_snn_navigation",
    "run_navigation",
]
