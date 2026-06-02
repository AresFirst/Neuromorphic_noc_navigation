"""路径辅助函数。"""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_project_path(*parts: str) -> Path:
    return project_root().joinpath(*parts)
