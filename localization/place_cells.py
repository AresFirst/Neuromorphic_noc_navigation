"""位置细胞层 (Place Cell Layer)。

灵感来源于哺乳动物海马体 (hippocampus) 的位置细胞：
- 每个位置细胞在动物处于特定空间位置时发放最大
- 发放率随距离增大呈高斯衰减
- 多个位置细胞的群体活动可以唯一确定空间位置

本模块将离散图节点建模为位置野中心，提供两种查询方式：
- activations(): 软激活，返回所有节点的激活值（高斯相似度）
- winner_take_all(): 硬分配，返回最近的节点 ID
"""

from __future__ import annotations

import math


class PlaceCellLayer:
    """位置细胞层：基于高斯感受野的位置→节点匹配。

    每个图节点作为一个"位置野"的中心，节点坐标为 (node_x, node_y)。
    当查询位置接近某节点时，该节点的激活值接近 1.0；
    远离时激活值按 exp(-distance² / (2σ²)) 衰减。

    sigma 参数控制位置野的宽度：
    - sigma 小：定位精确但要求 Agent 必须在节点附近
    - sigma 大：定位宽容但可能在节点密集区产生歧义
    """

    def __init__(
        self,
        node_positions: dict[int, tuple[float, float]],
        sigma: float = 0.1,
    ):
        """初始化位置细胞层。

        Args:
            node_positions: {节点ID: (x坐标, y坐标)} 字典。
                            坐标通常在 [0, 1] 归一化范围内。
            sigma: 高斯感受野的标准差，控制每个位置野的宽度。
                   默认 0.1（对应图中约 0.1 单位距离内激活 > 60%）。

        Raises:
            ValueError: 如果 sigma <= 0 或 node_positions 为空。
        """
        if sigma <= 0:
            raise ValueError("sigma must be positive")
        if not node_positions:
            raise ValueError("node_positions must not be empty")
        # 将节点坐标标准化为 (int, (float, float)) 格式
        self.node_positions = {
            int(node): (float(position[0]), float(position[1]))
            for node, position in node_positions.items()
        }
        self.sigma = float(sigma)

    def activations(self, x: float, y: float) -> dict[int, float]:
        """计算所有节点对查询位置 (x, y) 的软激活值（高斯相似度）。

        Args:
            x: 查询位置的 x 坐标。
            y: 查询位置的 y 坐标。

        Returns:
            {节点ID: 激活值} 字典。激活值 ∈ (0, 1]，值越大越接近。
            激活公式: exp(-distance² / (2·sigma²))
        """
        result: dict[int, float] = {}
        for node, (node_x, node_y) in self.node_positions.items():
            # 欧氏距离的平方，避免 sqrt 计算
            distance_sq = (float(x) - node_x) ** 2 + (float(y) - node_y) ** 2
            # 高斯核：距离越小激活越大，sigma 控制衰减速度
            result[node] = math.exp(-distance_sq / (2.0 * self.sigma**2))
        return result

    def winner_take_all(self, x: float, y: float) -> int:
        """硬分配：返回激活值最大的节点 ID（即最近节点）。

        这实现了"将连续坐标捕捉到最近离散图节点"的定位功能。

        Args:
            x: 查询位置的 x 坐标。
            y: 查询位置的 y 坐标。

        Returns:
            激活值最大的节点 ID。平局时返回 ID 最小的节点。

        实现细节: 用 min + 负激活值实现 argmax，
        node ID 作为 tie-breaker（平局时选更小 ID）。
        """
        activations = self.activations(x, y)
        # (-activation, node) 排序：激活越大负值越小，所以 min 选出最大激活
        # 平局时 node ID 小的排前面
        return min(activations, key=lambda node: (-activations[node], node))
