"""Noxim 输出解析: 从 stdout 文本或 JSON stats 文件中提取性能指标。

支持两种解析模式:
1. stdout 文本解析 (parse_noxim_output): 使用正则表达式匹配指标行
2. JSON stats 文件解析 (parse_noxim_stats_file/payload): 从结构化 JSON 提取

解析的指标包括:
- 执行周期数、收发包/flit 数量
- 全局平均延迟 (cycles)、最大延迟
- 网络吞吐量 (flits/cycle)
- 总能量/动态能量/静态能量 (J)、功率

为向后兼容，添加 legacy 别名:
- average_latency → global_average_delay_cycles
- throughput → network_throughput_flits_per_cycle
- energy → total_energy_j
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# 浮点数匹配正则: 支持正负号、科学计数法
_NUMBER_RE = r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"


def _extract_metric(text: str, labels: list[str]) -> float | None:
    """从文本中用多个候选标签名提取浮点数值。

    匹配模式: Label: <number> 或 Label = <number> (大小写不敏感)。

    Args:
        text: Noxim stdout 文本。
        labels: 候选标签名列表（依次尝试）。

    Returns:
        提取的浮点值或 None。
    """
    for label in labels:
        pattern = re.compile(
            rf"{re.escape(label)}\s*[:=]\s*{_NUMBER_RE}",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def _with_legacy_aliases(parsed: dict) -> dict:
    """为解析结果添加向后兼容的别名键。

    旧版代码可能使用这些简化名访问指标。
    """
    parsed["average_latency"] = parsed.get("global_average_delay_cycles")
    parsed["throughput"] = parsed.get("network_throughput_flits_per_cycle")
    parsed["energy"] = parsed.get("total_energy_j")
    return parsed


def parse_noxim_output(stdout_text: str) -> dict:
    """从 Noxim 的 stdout 文本中提取性能指标。

    这是旧版 Noxim (无 JSON stats 输出) 的解析方式。
    当 JSON stats 文件不可用时作为回退方案。

    Args:
        stdout_text: Noxim 的完整 stdout 字符串。

    Returns:
        指标字典，值可能是 float 或 None (提取失败时)。
        包含 legacy 别名键。
    """
    # 提取仿真执行周期数
    executed_cycles = None
    executed_match = re.search(
        r"Noxim simulation completed\.\s*\((\d+)\s+cycles executed\)",
        stdout_text,
        re.IGNORECASE,
    )
    if executed_match:
        try:
            executed_cycles = float(executed_match.group(1))
        except ValueError:
            executed_cycles = None

    parsed = {
        "executed_cycles": executed_cycles,
        "total_received_packets": _extract_metric(stdout_text, ["Total received packets"]),
        "total_received_flits": _extract_metric(stdout_text, ["Total received flits"]),
        "received_ideal_flits_ratio": _extract_metric(stdout_text, ["Received/Ideal flits Ratio"]),
        "average_wireless_utilization": _extract_metric(stdout_text, ["Average wireless utilization"]),
        "global_average_delay_cycles": _extract_metric(
            stdout_text, ["Global average delay (cycles)", "Average latency"]
        ),
        "max_delay_cycles": _extract_metric(stdout_text, ["Max delay (cycles)"]),
        "network_throughput_flits_per_cycle": _extract_metric(
            stdout_text, ["Network throughput (flits/cycle)", "Throughput"]
        ),
        "average_ip_throughput_flits_per_cycle_per_ip": _extract_metric(
            stdout_text, ["Average IP throughput (flits/cycle/IP)"]
        ),
        "total_energy_j": _extract_metric(stdout_text, ["Total energy (J)", "Energy"]),
        "dynamic_energy_j": _extract_metric(stdout_text, ["Dynamic energy (J)"]),
        "static_energy_j": _extract_metric(stdout_text, ["Static energy (J)"]),
        "power": _extract_metric(stdout_text, ["Power"]),
    }
    return _with_legacy_aliases(parsed)


def parse_noxim_stats_payload(payload: dict) -> dict:
    """从 Noxim JSON stats 字典中提取性能指标。

    较新的 Noxim 版本支持 `-stats_format json` 输出，
    比 stdout regex 解析更可靠。

    Args:
        payload: Noxim JSON stats 的解析字典。

    Returns:
        指标字典。优先从 payload["summary"] 提取，回退到顶层键。
    """
    # JSON stats 中指标通常在 "summary" 子对象下
    summary = payload.get("summary", payload)
    parsed = {
        "executed_cycles": summary.get("executed_cycles"),
        "total_received_packets": summary.get("total_received_packets"),
        "total_received_flits": summary.get("total_received_flits"),
        "received_ideal_flits_ratio": summary.get("received_ideal_flits_ratio"),
        "average_wireless_utilization": summary.get("average_wireless_utilization"),
        "global_average_delay_cycles": summary.get("global_average_delay_cycles"),
        "max_delay_cycles": summary.get("max_delay_cycles"),
        "network_throughput_flits_per_cycle": summary.get("network_throughput_flits_per_cycle"),
        "average_ip_throughput_flits_per_cycle_per_ip": summary.get(
            "average_ip_throughput_flits_per_cycle_per_ip"
        ),
        "total_energy_j": summary.get("total_energy_j"),
        "dynamic_energy_j": summary.get("dynamic_energy_j"),
        "static_energy_j": summary.get("static_energy_j"),
        "power": summary.get("power"),
    }
    return _with_legacy_aliases(parsed)


def parse_noxim_stats_file(path: str | Path) -> dict:
    """从 JSON stats 文件中读取并解析 Noxim 指标。

    Args:
        path: JSON stats 文件路径。

    Returns:
        指标字典。
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_noxim_stats_payload(payload)
