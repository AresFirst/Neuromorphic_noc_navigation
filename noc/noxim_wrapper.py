from __future__ import annotations

import subprocess
from pathlib import Path

from .parse_noxim_output import parse_noxim_output


def run_noxim(
    noxim_bin: str | None,
    config_path: str | None,
    traffic_table_path: str,
    output_dir: str,
) -> dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if not noxim_bin or not Path(noxim_bin).exists():
        return {
            "status": "skipped",
            "reason": "Noxim binary not found",
        }

    cmd = [noxim_bin]
    if config_path:
        cmd.extend(["--config", config_path])
    cmd.extend(["--traffic-table", traffic_table_path])

    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=output_path)
    except Exception as exc:  # pragma: no cover - binary-dependent
        return {
            "status": "failed",
            "reason": f"Failed to execute Noxim: {exc}",
        }

    stdout_path = output_path / "noxim_stdout.txt"
    stderr_path = output_path / "noxim_stderr.txt"
    stdout_path.write_text(completed.stdout or "", encoding="utf-8")
    stderr_path.write_text(completed.stderr or "", encoding="utf-8")

    parsed = parse_noxim_output(completed.stdout or "")
    status = "ok" if completed.returncode == 0 else "failed"
    return {
        "status": status,
        "returncode": completed.returncode,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "parsed": parsed,
    }
