"""中继控制器 (Relay Controller)。

提供对图中边的动态修改能力，用于模拟 NoC 中的运行时变化:
- 链路故障: block_edge() 将边标记为 "blocked"
- 链路拥塞: penalize_edge() 将边的延迟乘以惩罚因子
- 恢复: restore_edge() 将边恢复到原始状态

所有修改在内部副本上进行（通过 G.copy()），不破坏原始图。
边的原始延迟保存为 original_delay_ms 属性，用于恢复操作。

典型使用场景:
    controller = RelayController(graph)
    controller.block_edge(5, 12)  # 模拟链路 (5→12) 故障
    modified_graph = controller.get_graph()
    run_loihi_wavefront(modified_graph, start, target)  # 在修改后的图上重规划
"""

from __future__ import annotations

import networkx as nx


class RelayController:
    """图的动态边状态控制器。

    在不破坏原始图的前提下，对边的延迟和状态进行运行时修改。
    可以模拟 NoC 中的链路故障、拥塞等动态场景，
    用于测试 SNN 波前路由的鲁棒性和重规划能力。
    """

    def __init__(self, G: nx.DiGraph):
        """创建图控制器。

        对原图进行深拷贝，并在拷贝上操作。
        为每条边保存 original_delay_ms 属性（如果尚未存在）。

        Args:
            G: NetworkX 有向图（不会被修改）。
        """
        # 深拷贝：所有修改在副本上进行，保护原图
        self._graph = G.copy()
        # 确保每条边都有 original_delay_ms，用于后续恢复
        for _u, _v, attrs in self._graph.edges(data=True):
            if "original_delay_ms" not in attrs:
                attrs["original_delay_ms"] = int(attrs.get("delay_ms", 1))

    def _edge_attrs(self, u: int, v: int) -> dict:
        """获取边 (u, v) 的属性字典，边不存在时抛出异常。

        Args:
            u: 源节点 ID。
            v: 目标节点 ID。

        Returns:
            边属性字典（可变引用）。

        Raises:
            ValueError: 边不存在。
        """
        if not self._graph.has_edge(u, v):
            raise ValueError(f"edge ({u}, {v}) does not exist")
        return self._graph[u][v]

    def block_edge(self, u: int, v: int) -> None:
        """阻塞边 (u, v)：将其状态设为 "blocked"。

        波前传播算法会跳过 state="blocked" 的边。

        Args:
            u: 源节点 ID。
            v: 目标节点 ID。
        """
        attrs = self._edge_attrs(u, v)
        attrs["state"] = "blocked"

    def penalize_edge(self, u: int, v: int, factor: float) -> None:
        """惩罚边 (u, v)：将其延迟乘以 factor，状态设为 "penalized"。

        这模拟链路拥塞场景：延迟增加，但链路仍然可用。

        Args:
            u: 源节点 ID。
            v: 目标节点 ID。
            factor: 惩罚倍数（必须为正）。factor=5 表示延迟变为原来的 5 倍。

        Raises:
            ValueError: factor <= 0。
        """
        if factor <= 0:
            raise ValueError("factor must be positive")
        attrs = self._edge_attrs(u, v)
        # 确保 original_delay_ms 已保存
        original_delay_ms = int(attrs.get("original_delay_ms", attrs.get("delay_ms", 1)))
        attrs["original_delay_ms"] = original_delay_ms
        # 新延迟 = 原始延迟 × 惩罚因子，最小为 1
        attrs["delay_ms"] = max(1, int(round(original_delay_ms * float(factor))))
        attrs["state"] = "penalized"

    def restore_edge(self, u: int, v: int) -> None:
        """恢复边 (u, v)：重置延迟和状态到原始值。

        Args:
            u: 源节点 ID。
            v: 目标节点 ID。
        """
        attrs = self._edge_attrs(u, v)
        original_delay_ms = int(attrs.get("original_delay_ms", attrs.get("delay_ms", 1)))
        attrs["delay_ms"] = original_delay_ms
        attrs["original_delay_ms"] = original_delay_ms
        attrs["state"] = "normal"

    def get_graph(self) -> nx.DiGraph:
        """返回当前（可能已修改的）图副本。

        Returns:
            修改后的图。调用方可以用它运行波前路由或其他算法。
        """
        return self._graph
