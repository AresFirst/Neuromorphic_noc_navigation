from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.loihi_delay_demo import run_loihi_delay_demo
from loihi_planner.loihi_lif_demo import run_loihi_lif_demo
from loihi_planner.loihi_small_wavefront_demo import run_loihi_small_wavefront_demo
from noc.noxim_wrapper import run_noxim
from noc.traffic_table import save_sample_noxim_traffic_table


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    results_dir = repo_root / "results" / "week1"
    results_dir.mkdir(parents=True, exist_ok=True)

    backend_check = check_brian2loihi_available()
    (results_dir / "backend_check.json").write_text(
        json.dumps(backend_check, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lif_demo = run_loihi_lif_demo()
    delay_demo = run_loihi_delay_demo()
    wavefront_demo = run_loihi_small_wavefront_demo()
    loihi_summary = {
        "lif_demo": lif_demo,
        "delay_demo": delay_demo,
        "wavefront_demo": wavefront_demo,
    }
    (results_dir / "loihi_demo_summary.json").write_text(
        json.dumps(loihi_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    traffic_table_path = results_dir / "sample_traffic_table.txt"
    save_sample_noxim_traffic_table(str(traffic_table_path))

    noxim_config_path = repo_root / "configs" / "noxim.yaml"
    noxim_config = yaml.safe_load(noxim_config_path.read_text(encoding="utf-8")) or {}
    noxim_result = run_noxim(
        noxim_bin=noxim_config.get("noxim_bin"),
        config_path=noxim_config.get("noxim_config_path"),
        traffic_table_path=str(traffic_table_path),
        output_dir=str(results_dir),
    )

    install_hint = "Install Brian2Loihi and rerun this script to enable the Loihi demos."
    summary = {
        "backend_check": backend_check,
        "loihi_demo_summary": loihi_summary,
        "noxim_result": noxim_result,
        "notes": (
            "Brian2Loihi is unavailable in this environment."
            if not backend_check["available"]
            else "Brian2Loihi demo completed."
        ),
        "install_hint": install_hint if not backend_check["available"] else None,
    }
    (results_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if not backend_check["available"]:
        print(install_hint)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
