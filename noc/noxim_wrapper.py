"""Noxim 模拟器封装: 通过子进程调用 Noxim 周期精确 NoC 模拟器。

Noxim 是一个 C++ 实现的开源 NoC 周期精确模拟器 (https://github.com/davidepatti/noxim)。
本模块封装子进程调用、参数构造和结果收集。

命令行构造:
    <noxim_bin>
      -config <config_path>       # Noxim 配置 (路由算法、缓冲等)
      -power <power_path>         # 功耗模型
      [-dimx <cols>] [-dimy <rows>]  # Mesh 尺寸
      [-size <ps> <ps>]           # 包大小
      [-seed <seed>]              # 随机种子
      [-warmup <cycles>]          # 预热周期
      [-sim <cycles>]             # 仿真总周期
      -traffic <mode> <file>      # 流量模式 (table/hardcoded) + 文件路径
      -stats_format <format>      # 统计输出格式 (json)
      -stats_file <path>          # 统计输出路径

结果收集优先级:
    1. 首先尝试 parse_noxim_stats_file (JSON format, 最精确)
    2. 回退到 parse_noxim_output (stdout regex)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .parse_noxim_output import parse_noxim_output, parse_noxim_stats_file


def _resolve_path(path: str | None) -> Path | None:
    """展开用户主目录 (~) 并转为 Path 对象。

    Args:
        path: 路径字符串或 None。

    Returns:
        Path 对象或 None。
    """
    if not path:
        return None
    return Path(path).expanduser()


def _default_power_path(noxim_bin: Path | None, config_path: Path | None) -> Path | None:
    """根据 Noxim 二进制和配置路径推断 power.yaml 的位置。

    尝试顺序:
    1. <noxim_bin目录>/power.yaml
    2. <config目录>/../bin/power.yaml

    Args:
        noxim_bin: Noxim 二进制路径。
        config_path: Noxim 配置文件路径。

    Returns:
        power.yaml 的 Path 或 None。
    """
    if noxim_bin is not None:
        candidate = noxim_bin.parent / "power.yaml"
        if candidate.exists():
            return candidate
    if config_path is not None:
        candidate = config_path.parent.parent / "bin" / "power.yaml"
        if candidate.exists():
            return candidate
    return None


def _stats_file_path(output_path: Path) -> Path:
    """统计文件的标准路径: <output_dir>/noxim_stats.json"""
    return output_path / "noxim_stats.json"


def run_noxim(
    noxim_bin: str | None,
    config_path: str | None,
    traffic_table_path: str,
    output_dir: str,
    *,
    power_path: str | None = None,
    traffic_mode: str = "table",
    mesh_rows: int | None = None,
    mesh_cols: int | None = None,
    simulation_time: int | None = None,
    warmup_time: int | None = None,
    seed: int | None = None,
    packet_size: int | None = None,
    stats_format: str = "json",
) -> dict:
    """运行 Noxim 仿真。

    所有的 None 参数在构造命令行时会被省略，使用 Noxim 配置文件中的默认值。

    Args:
        noxim_bin: Noxim 二进制路径 (None 时返回 skipped)。
        config_path: Noxim 配置文件路径。
        traffic_table_path: 流量文件路径。
        output_dir: 输出目录。
        power_path: 功耗模型路径 (None 时自动推断)。
        traffic_mode: 流量模式: "table" 或 "hardcoded"。
        mesh_rows, mesh_cols: Mesh 尺寸 (覆盖配置文件)。
        simulation_time: 仿真总周期数 (覆盖配置文件)。
        warmup_time: 预热周期数。
        seed: 随机种子。
        packet_size: 包大小 flits (覆盖配置文件)。
        stats_format: 统计输出格式 (通常 "json")。

    Returns:
        字典:
        - status: "ok" | "skipped" | "failed"
        - returncode: 返回码 (ok/failed 时)
        - command: 执行的完整命令
        - stdout_path / stderr_path: stdout/stderr 输出文件路径
        - stats_path: JSON 统计文件路径
        - parsed: {指标名: 值} 字典
        - reason: 失败/跳过原因
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 验证必需文件存在
    noxim_bin_path = _resolve_path(noxim_bin)
    if noxim_bin_path is None or not noxim_bin_path.exists():
        return {"status": "skipped", "reason": "Noxim binary not found"}

    config_path_obj = _resolve_path(config_path)
    if config_path_obj is None or not config_path_obj.exists():
        return {"status": "skipped", "reason": "Noxim configuration file not found"}

    traffic_path = _resolve_path(traffic_table_path)
    if traffic_path is None or not traffic_path.exists():
        return {"status": "failed", "reason": "Traffic file not found"}

    power_path_obj = _resolve_path(power_path) or _default_power_path(noxim_bin_path, config_path_obj)
    if power_path_obj is None or not power_path_obj.exists():
        return {"status": "skipped", "reason": "Noxim power file not found"}

    # 构造 Noxim 命令行
    stats_path = _stats_file_path(output_path)
    cmd = [
        str(noxim_bin_path),
        "-config", str(config_path_obj),
        "-power", str(power_path_obj),
    ]

    # 可选参数: 仅在指定时添加（覆盖配置文件值）
    if mesh_cols is not None:
        cmd.extend(["-dimx", str(int(mesh_cols))])
    if mesh_rows is not None:
        cmd.extend(["-dimy", str(int(mesh_rows))])
    if packet_size is not None:
        packet_size = int(packet_size)
        cmd.extend(["-size", str(packet_size), str(packet_size)])  # min_size, max_size
    if seed is not None:
        cmd.extend(["-seed", str(int(seed))])
    if warmup_time is not None:
        cmd.extend(["-warmup", str(int(warmup_time))])
    if simulation_time is not None:
        cmd.extend(["-sim", str(int(simulation_time))])
    if traffic_mode:
        cmd.extend(["-traffic", traffic_mode, str(traffic_path)])
    # JSON 格式统计输出
    cmd.extend(["-stats_format", stats_format, "-stats_file", str(stats_path)])

    # 执行子进程
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=output_path)
    except Exception as exc:  # pragma: no cover - binary-dependent
        return {"status": "failed", "reason": f"Failed to execute Noxim: {exc}", "command": cmd}

    # 保存 stdout/stderr 到文件，方便调试
    stdout_path = output_path / "noxim_stdout.txt"
    stderr_path = output_path / "noxim_stderr.txt"
    stdout_text = completed.stdout or ""
    stderr_text = completed.stderr or ""
    stdout_path.write_text(stdout_text, encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")

    # 解析输出: 优先 JSON stats，回退到 stdout regex
    parsed = {}
    if stats_path.exists():
        try:
            parsed = parse_noxim_stats_file(stats_path)
        except Exception:
            parsed = {}
    if not parsed:
        parsed = parse_noxim_output(stdout_text)

    status = "ok" if completed.returncode == 0 else "failed"
    result = {
        "status": status,
        "returncode": completed.returncode,
        "command": cmd,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "stats_path": str(stats_path) if stats_path.exists() else None,
        "parsed": parsed,
    }
    if completed.returncode != 0:
        result["reason"] = "Noxim exited with a non-zero status"
    return result


def run_noxim_with_traffic_table(
    noxim_bin: str | None,
    config_path: str | None,
    traffic_table_path: str,
    output_dir: str,
    **kwargs,
) -> dict:
    """使用 traffic table 模式运行 Noxim 的便捷函数。

    流量模式为 "table": Noxim 读取聚合统计流量表。
    """
    return run_noxim(
        noxim_bin=noxim_bin, config_path=config_path,
        traffic_table_path=traffic_table_path, output_dir=output_dir,
        traffic_mode="table", **kwargs,
    )


def run_noxim_with_hardcoded_traffic(
    noxim_bin: str | None,
    config_path: str | None,
    traffic_path: str,
    output_dir: str,
    **kwargs,
) -> dict:
    """使用 hardcoded 模式运行 Noxim 的便捷函数。

    流量模式为 "hardcoded": Noxim 逐周期读取精确的注入指令。
    """
    return run_noxim(
        noxim_bin=noxim_bin, config_path=config_path,
        traffic_table_path=traffic_path, output_dir=output_dir,
        traffic_mode="hardcoded", **kwargs,
    )
