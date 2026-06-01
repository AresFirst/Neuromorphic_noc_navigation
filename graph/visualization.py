"""图可视化模块。

使用 Matplotlib 渲染 NoC 图的拓扑结构，支持路径高亮叠加。
输出高分辨率 PNG 图片。

渲染规则:
- 非路径边: 浅灰色细线
- 路径边: 红色粗线
- 节点: 按 region 属性着色 (tab10 colormap)
- 起点: 绿色方块
- 终点: 金色星形
"""

from __future__ import annotations

import os
from pathlib import Path

# ---- Matplotlib 配置 ----
# 在导入 matplotlib 之前设置缓存目录和渲染后端
# 这样在无头环境 / CI 中不会因缺少显示设备而崩溃
mpl_cache_dir = Path(__file__).resolve().parents[1] / ".matplotlib-cache"
mpl_cache_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(mpl_cache_dir))

import matplotlib

# 强制使用 Agg 后端（无 GUI 渲染），避免 plt.show() 阻塞
matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt


def plot_graph_with_path(
    G,
    path: list[int] | None,
    save_path: str,
    title: str | None = None,
) -> None:
    """绘制图拓扑并高亮指定路径。

    Args:
        G: NetworkX 有向图（节点需有 x, y, region 属性）。
        path: 要突出显示的路径节点列表（可以为 None，不显示路径）。
        save_path: 输出 PNG 文件路径。
        title: 图片标题（可选）。
    """
    # 提取节点坐标: {node_id: (x, y)}
    positions = {node: (float(attrs["x"]), float(attrs["y"])) for node, attrs in G.nodes(data=True)}
    fig, ax = plt.subplots(figsize=(8, 6), dpi=180)

    # 确定路径边集合（用于高亮）
    path_edges = set(zip(path[:-1], path[1:])) if path and len(path) >= 2 else set()
    # 先画非路径边（灰色背景），再画路径边（红色前景）
    for source, target, _attrs in G.edges(data=True):
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        if (source, target) in path_edges:
            # 路径边: 红色粗线，高 z-order 确保在上面
            ax.plot([x1, x2], [y1, y2], color="#d62728", linewidth=2.4, alpha=0.95, zorder=2)
        else:
            # 非路径边: 浅灰色细线，低 z-order
            ax.plot([x1, x2], [y1, y2], color="#9aa0a6", linewidth=0.5, alpha=0.25, zorder=1)

    # 节点着色: 按 region 属性使用 tab10 colormap
    regions = [int(G.nodes[node].get("region", 0)) for node in G.nodes()]
    xs = [positions[node][0] for node in G.nodes()]
    ys = [positions[node][1] for node in G.nodes()]
    ax.scatter(xs, ys, c=regions, cmap="tab10", s=18, edgecolors="white", linewidths=0.3, zorder=3)

    # 起点和终点的特殊标记
    if path:
        start = path[0]
        target = path[-1]
        sx, sy = positions[start]
        tx, ty = positions[target]
        # 起点: 绿色方块
        ax.scatter([sx], [sy], s=110, marker="s", color="#2ca02c", edgecolors="black", linewidths=0.7, zorder=4)
        # 终点: 金色星形
        ax.scatter([tx], [ty], s=135, marker="*", color="#ffbf00", edgecolors="black", linewidths=0.7, zorder=4)

    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")  # 隐藏坐标轴
    if title:
        ax.set_title(title, fontsize=11)
    fig.tight_layout(pad=0.2)

    output = Path(save_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)  # 关闭图形释放内存
