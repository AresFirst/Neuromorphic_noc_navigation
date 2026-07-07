"""SNN planner integration layer."""

from __future__ import annotations

# snn 包目前只暴露 wavefront 运行入口；具体使用 Loihi 还是 CPU fallback 由 planner 决定。
from .planner import run_wavefront

__all__ = ["run_wavefront"]
