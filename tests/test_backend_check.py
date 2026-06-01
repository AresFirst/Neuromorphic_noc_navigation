"""测试后端可用性检测。

验证 check_brian2loihi_available() 在任何环境下都不会崩溃，
并且返回结构正确的字典。
"""

from loihi_planner.backend_check import check_brian2loihi_available


def test_backend_check_does_not_crash():
    """验证后端检测函数: 返回结构必须包含必需键且 available 为 bool。

    即使 Brian2Loihi 未安装，也不应抛出异常，
    而是返回 available=False 和 error 描述。
    """
    result = check_brian2loihi_available()
    # 必需键: available, brian2_version, brian2loihi_version, error
    assert {"available", "brian2_version", "brian2loihi_version", "error"} <= set(result)
    assert isinstance(result["available"], bool)
    # 不可用时必须有 error 信息
    if not result["available"]:
        assert result["error"]
