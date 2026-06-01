"""动态起点定位模块 (localization)。

提供从连续二维坐标到离散图节点的定位能力，灵感来源于哺乳动物的空间导航系统：
- GridCellEncoder: 模拟内嗅皮层网格细胞的多尺度周期编码
- PlaceCellLayer: 模拟海马体位置细胞的高斯感受野
- estimate_start_node_from_position: 一站式定位入口
"""

from .dynamic_start import estimate_start_node_from_position
from .grid_cells import GridCellEncoder
from .place_cells import PlaceCellLayer

__all__ = [
    "GridCellEncoder",
    "PlaceCellLayer",
    "estimate_start_node_from_position",
]
