"""Brian2Loihi 后端可用性检测。

提供 check_brian2loihi_available() 函数，
用于在实验开始前检测 Brian2 和 Brian2Loihi 的安装状态和版本信息。

检测逻辑:
1. 尝试导入 brian2，获取版本号
2. 尝试导入 brian2loihi 或 brian2_loihi，获取版本号
3. 两者都有且版本可读 → available=True
"""

from __future__ import annotations

import os
from importlib import metadata
from pathlib import Path

# 设置 matplotlib 缓存目录（避免在检测阶段写入用户主目录）
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MPL_CACHE = _PROJECT_ROOT / ".matplotlib-cache"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))


def _module_version(module_name: str, distribution_names: tuple[str, ...] = ()) -> str | None:
    """获取模块的版本号。

    先尝试 module.__version__，失败后尝试 importlib.metadata.version()。
    distribution_names 是 pip 包名（可能与 import 名不同）。

    Args:
        module_name: Python import 模块名。
        distribution_names: pip 包名候选列表。

    Returns:
        版本字符串或 None（如果导入失败或无版本信息）。
    """
    try:
        module = __import__(module_name)
    except Exception:
        return None

    # 优先使用模块自带的 __version__
    version = getattr(module, "__version__", None)
    if version:
        return str(version)
    # 回退到 pip 包元数据
    for distribution_name in (module_name, *distribution_names):
        try:
            return str(metadata.version(distribution_name))
        except Exception:
            continue
    return None


def _import_first_available(module_names: tuple[str, ...]) -> tuple[str | None, Exception | None]:
    """按顺序尝试导入模块名列表，返回第一个成功导入的名称。

    用于处理 brian2loihi / brian2_loihi 命名不一致的情况。

    Args:
        module_names: 候选模块名元组。

    Returns:
        (成功导入的模块名, None) 或 (None, 最后一个异常)。
    """
    last_error: Exception | None = None
    for module_name in module_names:
        try:
            __import__(module_name)
            return module_name, None
        except Exception as exc:
            last_error = exc
    return None, last_error


def check_brian2loihi_available() -> dict:
    """检测 Brian2Loihi 环境是否可用。

    Returns:
        字典，包含以下键:
        - available (bool): 是否可用
        - brian2_version (str|None): brian2 版本
        - brian2loihi_version (str|None): brian2loihi 版本
        - brian2loihi_module (str|None): 实际导入的模块名
        - error (str|None): 不可用时的错误描述
    """
    error_parts: list[str] = []

    # 检测 brian2
    brian2_version = _module_version("brian2")
    if brian2_version is None:
        try:
            __import__("brian2")
        except Exception as exc:  # pragma: no cover - import failure path
            error_parts.append(f"brian2 import failed: {exc}")

    # 检测 brian2loihi（先尝试 brian2loihi，再尝试 brian2_loihi）
    brian2loihi_module, brian2loihi_error = _import_first_available(("brian2loihi", "brian2_loihi"))
    brian2loihi_version = None
    if brian2loihi_module is not None:
        brian2loihi_version = _module_version(
            brian2loihi_module,
            distribution_names=("brian2-loihi", "Brian2Loihi"),
        )
    else:
        error_parts.append(f"brian2loihi import failed: {brian2loihi_error}")

    # 两个包都必须可用
    available = brian2loihi_version is not None
    if available and brian2_version is None:
        available = False
        error_parts.append("brian2 is missing")

    error = None
    if not available:
        if error_parts:
            error = "; ".join(error_parts)
        else:
            error = "Brian2Loihi is not available in this environment."

    return {
        "available": available,
        "brian2_version": brian2_version,
        "brian2loihi_version": brian2loihi_version,
        "brian2loihi_module": brian2loihi_module,
        "error": error,
    }
