"""Compatibility namespace for the Brian2Loihi wavefront API."""

from __future__ import annotations

# nmn 命名空间保留给旧代码兼容；当前真实实现委托给 loihi_planner。
from . import loihi

__all__ = ["loihi"]
