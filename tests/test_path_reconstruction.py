"""测试路径重建。

验证 reconstruct_path_from_parent() 的正常路径重建和异常检测:
- 正常: 从 parent_trace 正确重建路径
- 异常: parent 链不可达 start 时抛出 ValueError
"""

import pytest

from loihi_planner.path_reconstruction import reconstruct_path_from_parent


def test_reconstruct_path_from_parent_returns_full_path():
    """验证正常重建: parent 链 4→3→1→0 → 正向路径 [0,1,3,4]."""
    # parent_trace: {节点: 父节点}
    parent_trace = {0: None, 1: 0, 2: 0, 3: 1, 4: 3}
    assert reconstruct_path_from_parent(parent_trace, 0, 4) == [0, 1, 3, 4]


def test_reconstruct_path_from_parent_raises_when_path_does_not_reach_start():
    """验证异常: parent 链形成闭环 (1→2→1)，从不经过 start=0。

    预期: 抛出 ValueError (循环检测或父节点为 None)。
    """
    parent_trace = {0: None, 1: 2, 2: 1}
    with pytest.raises(ValueError):
        reconstruct_path_from_parent(parent_trace, 0, 1)
