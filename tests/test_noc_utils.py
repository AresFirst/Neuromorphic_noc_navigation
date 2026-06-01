"""测试 NoC 工具函数。

验证:
- Noxim 二进制缺失时 run_noxim() 返回 skipped (优雅降级)
- parse_noxim_output() 正确从文本中提取所有指标
"""

from noc.noxim_wrapper import run_noxim
from noc.parse_noxim_output import parse_noxim_output
from noc.traffic_table import save_sample_noxim_traffic_table


def test_noxim_binary_missing_skips(tmp_path):
    """验证: noxim_bin=None 时返回 status="skipped"，不崩溃。

    tmp_path: pytest 提供的临时目录。
    """
    traffic_table = tmp_path / "traffic.txt"
    save_sample_noxim_traffic_table(str(traffic_table))

    result = run_noxim(
        noxim_bin=None,        # 模拟 Noxim 未安装
        config_path=None,
        traffic_table_path=str(traffic_table),
        output_dir=str(tmp_path),
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "Noxim binary not found"


def test_parse_noxim_output_extracts_known_metrics():
    """验证 stdout 解析: 从模拟的 Noxim 输出文本中正确提取所有指标。

    同时验证 legacy 别名 (average_latency → global_average_delay_cycles 等) 正常工作。
    """
    parsed = parse_noxim_output(
        """
        Average latency: 12.5
        Throughput = 0.91
        Power: 4.2
        Energy = 33.0
        """
    )
    # 原始键
    assert parsed["average_latency"] == 12.5
    assert parsed["global_average_delay_cycles"] == 12.5
    assert parsed["throughput"] == 0.91
    assert parsed["network_throughput_flits_per_cycle"] == 0.91
    assert parsed["power"] == 4.2
    assert parsed["energy"] == 33.0
    # legacy 别名
    assert parsed["total_energy_j"] == 33.0
