"""SUMO environment and map loading checks."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path


def _bundled_sumo_home() -> str | None:
    spec = importlib.util.find_spec("sumo")
    if spec is None or spec.origin is None:
        return None
    package_dir = Path(spec.origin).resolve().parent
    if (package_dir / "bin" / "sumo").exists():
        return str(package_dir)
    return None


def _sumo_candidates() -> list[str]:
    candidates: list[str] = []
    explicit = os.environ.get("SUMO_BINARY")
    if explicit:
        candidates.append(explicit)
    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        candidates.append(str(Path(sumo_home).expanduser() / "bin" / "sumo"))
    bundled = _bundled_sumo_home()
    if bundled:
        candidates.append(str(Path(bundled) / "bin" / "sumo"))
    on_path = shutil.which("sumo")
    if on_path:
        candidates.append(on_path)
    return list(dict.fromkeys(candidates))


def _sumo_gui_binary() -> str | None:
    explicit = os.environ.get("SUMO_GUI_BINARY")
    if explicit:
        return explicit
    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        candidate = Path(sumo_home).expanduser() / "bin" / "sumo-gui"
        if candidate.exists():
            return str(candidate)
    bundled = _bundled_sumo_home()
    if bundled:
        candidate = Path(bundled) / "bin" / "sumo-gui"
        if candidate.exists():
            return str(candidate)
    return shutil.which("sumo-gui")


def check_sumo_available() -> dict:
    sumo_gui_bin = _sumo_gui_binary()
    candidates = _sumo_candidates()
    if not candidates:
        return {
            "available": False,
            "sumo_bin": None,
            "sumo_gui_bin": sumo_gui_bin,
            "version": None,
            "error": "sumo executable not found on PATH",
            "install_hint": "Install Eclipse SUMO and set SUMO_BINARY or SUMO_HOME if it is not on PATH.",
        }

    errors: list[str] = []
    for sumo_bin in candidates:
        if not Path(sumo_bin).expanduser().exists():
            errors.append(f"{sumo_bin}: file does not exist")
            continue
        try:
            result = subprocess.run(
                [sumo_bin, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except Exception as exc:
            errors.append(f"{sumo_bin}: {exc}")
            continue

        output = (result.stdout or result.stderr or "").strip()
        first_line = output.splitlines()[0] if output else None
        looks_like_eclipse_sumo = bool(first_line and "sumo" in first_line.lower())
        if result.returncode == 0 and looks_like_eclipse_sumo:
            return {
                "available": True,
                "sumo_bin": sumo_bin,
                "sumo_gui_bin": sumo_gui_bin,
                "version": first_line,
                "error": None,
                "install_hint": None,
            }
        errors.append(f"{sumo_bin}: {output or f'exit code {result.returncode}'}")

    return {
        "available": False,
        "sumo_bin": candidates[0],
        "sumo_gui_bin": sumo_gui_bin,
        "version": None,
        "error": "No working Eclipse SUMO executable found. " + " | ".join(errors),
        "install_hint": "Install Eclipse SUMO and set SUMO_BINARY or SUMO_HOME if another command named 'sumo' shadows it.",
    }


def run_sumo_map_load_check(
    *,
    netxml_path: str | None = None,
    sumocfg_path: str | None = None,
    timeout_sec: int = 60,
) -> dict:
    """Run a headless SUMO load check for a net.xml or .sumocfg file."""
    status = check_sumo_available()
    if not status["available"]:
        return {"success": False, "status": status, "command": None, "stdout": "", "stderr": status["error"]}

    if sumocfg_path is None and netxml_path is None:
        raise ValueError("netxml_path or sumocfg_path must be provided")
    if sumocfg_path is not None:
        path = Path(sumocfg_path).expanduser()
        command = [
            status["sumo_bin"],
            "-c",
            str(path),
            "--duration-log.disable",
            "true",
            "--no-step-log",
            "true",
            "--end",
            "0",
        ]
    else:
        path = Path(netxml_path).expanduser()
        command = [
            status["sumo_bin"],
            "-n",
            str(path),
            "--duration-log.disable",
            "true",
            "--no-step-log",
            "true",
            "--end",
            "0",
        ]

    if not path.exists():
        return {
            "success": False,
            "status": status,
            "command": command,
            "stdout": "",
            "stderr": f"SUMO map file not found: {path}",
        }

    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_sec)
    return {
        "success": result.returncode == 0,
        "status": status,
        "command": command,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
