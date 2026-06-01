"""Brian2 / Brian2Loihi 后端加载器。

本模块是所有 Loihi SNN 仿真的入口基础设施。它负责:
1. 导入 brian2 和 brian2loihi (或 brian2_loihi)
2. 自动检测运行模式 (device 模式 vs object_api 模式)
3. 返回 Brian2LoihiBackend 对象供上游模块使用

两种运行模式:
- brian2_device 模式: 通过 brian2.set_device("brian2loihi") 使用 Brian2 设备接口
  这适用于使用 brian2.devices.device 机制的较旧版本
- object_api 模式: 直接创建 LoihiNeuronGroup、LoihiSynapses 等对象
  这适用于较新版本，API 更直观

自动检测逻辑:
  首先检查 brian2.devices.device.all_devices 中是否注册了 "brian2loihi" 或 "loihi"
  如果有 → device 模式
  如果导入的模块有 LoihiNetwork 属性 → object_api 模式
  都没有 → 返回错误
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 设置 matplotlib 缓存目录
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MPL_CACHE = _PROJECT_ROOT / ".matplotlib-cache"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))


@dataclass(frozen=True)
class Brian2LoihiBackend:
    """Brian2Loihi 后端描述对象（frozen dataclass）。

    Attributes:
        brian2: 导入的 brian2 模块对象。
        loihi_module: 导入的 brian2loihi (或 brian2_loihi) 模块对象。
        name: 后端名称（如 "brian2loihi"）。
        mode: 运行模式，"brian2_device" 或 "object_api"。
        device_name: device 模式下注册的设备名（如 "brian2loihi"），
                     object_api 模式下为 None。
    """
    brian2: Any  # brian2 模块
    loihi_module: Any  # brian2loihi 或 brian2_loihi 模块
    name: str  # 后端名称
    mode: str  # "brian2_device" 或 "object_api"
    device_name: str | None = None  # device 模式下注册的设备名


def _import_brian2loihi_module() -> tuple[Any | None, str | None, str | None]:
    """尝试导入 Brian2Loihi 模块。

    先尝试 "brian2loihi"，失败后尝试 "brian2_loihi"（包名在不同版本中不同）。

    Returns:
        (模块对象, 模块名, None) 成功时，
        (None, None, 错误消息) 失败时。
    """
    errors: list[str] = []
    for module_name in ("brian2loihi", "brian2_loihi"):
        try:
            module = __import__(module_name)
            return module, module_name, None
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
    return None, None, "; ".join(errors)


def load_brian2loihi_backend() -> tuple[Brian2LoihiBackend | None, str | None]:
    """加载并检测 Brian2Loihi 后端。

    这是整个 loihi_planner 模块的入口函数。
    所有需要运行 Loihi SNN 仿真的代码都应先调用此函数获取后端。

    加载流程:
    1. 导入 brian2
    2. 导入 brian2loihi (尝试两个候选名)
    3. 尝试设置 codegen.target = "numpy" (避免 Cython 编译缓存问题)
    4. 检测运行模式:
       a. 检查 brian2.devices 中是否注册了 Loihi 设备 → device 模式
       b. 检查是否有 LoihiNetwork 类 → object_api 模式
       c. 都没有 → 返回错误

    Returns:
        (Brian2LoihiBackend, None) 成功时，
        (None, 错误消息) 失败时。
    """
    # 步骤 1: 导入 brian2
    try:
        import brian2 as b2
    except Exception as exc:
        return None, f"brian2 import failed: {exc}"

    # 步骤 2: 导入 brian2loihi
    loihi_module, module_name, import_error = _import_brian2loihi_module()
    if import_error:
        return None, f"brian2loihi import failed: {import_error}"

    # 步骤 3: 设置 numpy 代码生成后端
    # 在受限环境或 macOS 上，Cython 编译可能写缓存到用户目录导致权限问题
    # 改为 numpy 后端更稳定
    try:
        b2.prefs.codegen.target = "numpy"
    except Exception:
        pass

    # 步骤 4a: 检查 device 模式
    try:
        from brian2.devices.device import all_devices
    except Exception as exc:
        all_devices = {}

    device_name: str | None = None
    for candidate in ("brian2loihi", "loihi"):
        if candidate in all_devices:
            device_name = candidate
            break

    if device_name is not None:
        # device 模式：通过 brian2.set_device() 使用
        return Brian2LoihiBackend(
            brian2=b2,
            loihi_module=loihi_module,
            name=module_name or device_name,
            mode="brian2_device",
            device_name=device_name,
        ), None

    # 步骤 4b: 检查 object_api 模式
    if hasattr(loihi_module, "LoihiNetwork"):
        # object_api 模式：直接创建 Loihi 对象
        return Brian2LoihiBackend(
            brian2=b2,
            loihi_module=loihi_module,
            name=module_name or "brian2_loihi",
            mode="object_api",
        ), None

    # 步骤 4c: 两种模式都不可用
    return None, "Brian2Loihi imported, but no supported backend API was found."
