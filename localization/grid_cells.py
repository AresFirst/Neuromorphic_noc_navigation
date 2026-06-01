"""网格细胞编码器 (Grid Cell Encoder)。

灵感来源于哺乳动物内嗅皮层 (entorhinal cortex) 的网格细胞：
- 网格细胞在动物经过空间中周期性格点时会发放
- 不同模块的网格细胞有不同的空间周期 (wavelength)
- 多个波长组合可以实现高精度、无歧义的空间编码

本模块将连续二维坐标 (x, y) 编码为高维周期向量，
可作为下游神经网络策略或定位解码器的输入。
"""

from __future__ import annotations

import math

import numpy as np


class GridCellEncoder:
    """网格细胞编码器：将 2D 位置映射为多尺度周期特征向量。

    对每个 (wavelength, phase) 组合，生成 6 个值：
    - sin/cos(x), sin/cos(y), sin/cos((x+y)/√2)
    包含 x、y 和对角线三个方向的投影，提供更丰富的空间信息。

    向量维度 = len(wavelengths) × len(phases) × 6
    默认: 4 × 3 × 6 = 72 维
    """

    def __init__(
        self,
        wavelengths: list[float] | None = None,
        phases: list[float] | None = None,
    ):
        """初始化网格细胞编码器。

        Args:
            wavelengths: 空间周期列表，越大编码越粗糙的空间尺度。
                         默认 [0.2, 0.4, 0.8, 1.6] 提供 4 个尺度的编码。
            phases: 相位偏移列表（弧度），多种相位减少周期歧义。
                    默认 [0, π/3, 2π/3]。

        Raises:
            ValueError: 如果 wavelengths 中有非正值。
        """
        # 多波长 = 多尺度：短波长精细局部定位，长波长消除大尺度歧义
        self.wavelengths = list(wavelengths or [0.2, 0.4, 0.8, 1.6])
        if any(value <= 0 for value in self.wavelengths):
            raise ValueError("wavelengths must be positive")
        # 多相位 = 更丰富的表示：不同相位偏移捕捉位置的不同"切片"
        self.phases = list(phases or [0.0, math.pi / 3.0, 2.0 * math.pi / 3.0])

    def encode(self, x: float, y: float) -> np.ndarray:
        """将连续坐标 (x, y) 编码为周期特征向量。

        Args:
            x: 二维空间的 x 坐标。
            y: 二维空间的 y 坐标。

        Returns:
            一维 numpy float 数组，长度为 len(wavelengths) × len(phases) × 6。
            默认返回 72 维向量。

        编码公式 (对每个 wavelength λ 和 phase φ):
            sin(2π/λ · dir + φ) 和 cos(2π/λ · dir + φ)
            其中 dir ∈ {x, y, (x+y)/√2}
        """
        values: list[float] = []
        for wavelength in self.wavelengths:
            # scale = 2π/λ，频率越高空间分辨率越精细
            scale = 2.0 * math.pi / wavelength
            for phase in self.phases:
                # x 方向投影
                values.append(math.sin(scale * x + phase))
                values.append(math.cos(scale * x + phase))
                # y 方向投影
                values.append(math.sin(scale * y + phase))
                values.append(math.cos(scale * y + phase))
                # 对角线方向投影 (x+y)/√2：提供对联合位置变化的敏感性
                values.append(math.sin(scale * (x + y) / math.sqrt(2.0) + phase))
                values.append(math.cos(scale * (x + y) / math.sqrt(2.0) + phase))
        return np.asarray(values, dtype=float)
