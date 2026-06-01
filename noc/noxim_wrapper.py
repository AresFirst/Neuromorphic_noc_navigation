from __future__ import annotations

import subprocess
from pathlib import Path

from .parse_noxim_output import parse_noxim_output, parse_noxim_stats_file


def _resolve_path(path: str | None) -> Path | None:
    if not path:
        return None
    return Path(path).expanduser()


def _default_power_path(noxim_bin: Path | None, config_path: Path | None) -> Path | None:
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
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    noxim_bin_path = _resolve_path(noxim_bin)
    if noxim_bin_path is None or not noxim_bin_path.exists():
        return {
            "status": "skipped",
            "reason": "Noxim binary not found",
        }

    config_path_obj = _resolve_path(config_path)
    if config_path_obj is None or not config_path_obj.exists():
        return {
            "status": "skipped",
            "reason": "Noxim configuration file not found",
        }

    traffic_path = _resolve_path(traffic_table_path)
    if traffic_path is None or not traffic_path.exists():
        return {
            "status": "failed",
            "reason": "Traffic file not found",
        }

    power_path_obj = _resolve_path(power_path) or _default_power_path(noxim_bin_path, config_path_obj)
    if power_path_obj is None or not power_path_obj.exists():
        return {
            "status": "skipped",
            "reason": "Noxim power file not found",
        }

    stats_path = _stats_file_path(output_path)
    cmd = [
        str(noxim_bin_path),
        "-config",
        str(config_path_obj),
        "-power",
        str(power_path_obj),
    ]

    if mesh_cols is not None:
        cmd.extend(["-dimx", str(int(mesh_cols))])
    if mesh_rows is not None:
        cmd.extend(["-dimy", str(int(mesh_rows))])
    if packet_size is not None:
        packet_size = int(packet_size)
        cmd.extend(["-size", str(packet_size), str(packet_size)])
    if seed is not None:
        cmd.extend(["-seed", str(int(seed))])
    if warmup_time is not None:
        cmd.extend(["-warmup", str(int(warmup_time))])
    if simulation_time is not None:
        cmd.extend(["-sim", str(int(simulation_time))])
    if traffic_mode:
        cmd.extend(["-traffic", traffic_mode, str(traffic_path)])
    cmd.extend(["-stats_format", stats_format, "-stats_file", str(stats_path)])

    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=output_path)
    except Exception as exc:  # pragma: no cover - binary-dependent
        return {
            "status": "failed",
            "reason": f"Failed to execute Noxim: {exc}",
            "command": cmd,
        }

    stdout_path = output_path / "noxim_stdout.txt"
    stderr_path = output_path / "noxim_stderr.txt"
    stdout_text = completed.stdout or ""
    stderr_text = completed.stderr or ""
    stdout_path.write_text(stdout_text, encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")

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
    return run_noxim(
        noxim_bin=noxim_bin,
        config_path=config_path,
        traffic_table_path=traffic_table_path,
        output_dir=output_dir,
        traffic_mode="table",
        **kwargs,
    )


def run_noxim_with_hardcoded_traffic(
    noxim_bin: str | None,
    config_path: str | None,
    traffic_path: str,
    output_dir: str,
    **kwargs,
) -> dict:
    return run_noxim(
        noxim_bin=noxim_bin,
        config_path=config_path,
        traffic_table_path=traffic_path,
        output_dir=output_dir,
        traffic_mode="hardcoded",
        **kwargs,
    )
