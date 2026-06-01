from pathlib import Path

import pandas as pd
import pytest

from noc.noxim_wrapper import run_noxim, run_noxim_with_traffic_table
from noc.parse_noxim_output import parse_noxim_output
from noc.traffic_table import save_noxim_hardcoded_traffic, save_sample_noxim_traffic_table


NOXIM_ROOT = Path("/Users/ares/code/noxim-master")
NOXIM_BIN = NOXIM_ROOT / "bin/noxim"
NOXIM_CONFIG = NOXIM_ROOT / "config_examples/default_configMeshNoHUB.yaml"
NOXIM_POWER = NOXIM_ROOT / "bin/power.yaml"


def test_run_noxim_with_traffic_table_skips_when_binary_missing(tmp_path):
    traffic_table_path = tmp_path / "traffic.txt"
    save_sample_noxim_traffic_table(str(traffic_table_path))
    result = run_noxim_with_traffic_table(None, None, str(traffic_table_path), str(tmp_path))
    assert result["status"] == "skipped"
    assert result["reason"] == "Noxim binary not found"


def test_parse_noxim_output_extracts_known_metrics():
    parsed = parse_noxim_output(
        """
        Noxim simulation completed. (1020 cycles executed)
        Total received packets: 7
        Total received flits: 42
        Received/Ideal flits Ratio: 0.5
        Average wireless utilization: 0.1
        Global average delay (cycles): 12.5
        Max delay (cycles): 18
        Network throughput (flits/cycle): 0.91
        Average IP throughput (flits/cycle/IP): 0.25
        Total energy (J): 33.0
        Dynamic energy (J): 4.2
        Static energy (J): 28.8
        """
    )
    assert parsed["executed_cycles"] == 1020.0
    assert parsed["total_received_packets"] == 7.0
    assert parsed["total_received_flits"] == 42.0
    assert parsed["received_ideal_flits_ratio"] == 0.5
    assert parsed["average_wireless_utilization"] == 0.1
    assert parsed["global_average_delay_cycles"] == 12.5
    assert parsed["average_latency"] == 12.5
    assert parsed["max_delay_cycles"] == 18.0
    assert parsed["network_throughput_flits_per_cycle"] == 0.91
    assert parsed["throughput"] == 0.91
    assert parsed["average_ip_throughput_flits_per_cycle_per_ip"] == 0.25
    assert parsed["total_energy_j"] == 33.0
    assert parsed["energy"] == 33.0
    assert parsed["dynamic_energy_j"] == 4.2
    assert parsed["static_energy_j"] == 28.8


@pytest.mark.skipif(
    not (NOXIM_BIN.exists() and NOXIM_CONFIG.exists() and NOXIM_POWER.exists()),
    reason="Local Noxim installation not available",
)
def test_run_noxim_with_real_binary_and_hardcoded_traffic(tmp_path):
    traffic_path = tmp_path / "hardcoded.txt"
    save_noxim_hardcoded_traffic(
        pd.DataFrame(
            [
                {
                    "cycle": 0,
                    "src_neuron": 0,
                    "dst_neuron": 1,
                    "src_core": 0,
                    "dst_core": 1,
                    "packet_type": "spike",
                    "packet_size": 1,
                }
            ]
        ),
        str(traffic_path),
    )

    result = run_noxim(
        str(NOXIM_BIN),
        str(NOXIM_CONFIG),
        str(traffic_path),
        str(tmp_path),
        power_path=str(NOXIM_POWER),
        traffic_mode="hardcoded",
        mesh_rows=4,
        mesh_cols=4,
        simulation_time=20,
        warmup_time=0,
        seed=0,
        packet_size=2,
    )

    assert result["status"] == "ok"
    assert result["stats_path"] is not None
    assert Path(result["stats_path"]).exists()
    assert result["parsed"]["total_received_packets"] >= 1
    assert result["parsed"]["global_average_delay_cycles"] is not None
