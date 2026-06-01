from noc.noxim_wrapper import run_noxim
from noc.parse_noxim_output import parse_noxim_output
from noc.traffic_table import save_sample_noxim_traffic_table


def test_noxim_binary_missing_skips(tmp_path):
    traffic_table = tmp_path / "traffic.txt"
    save_sample_noxim_traffic_table(str(traffic_table))

    result = run_noxim(
        noxim_bin=None,
        config_path=None,
        traffic_table_path=str(traffic_table),
        output_dir=str(tmp_path),
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "Noxim binary not found"


def test_parse_noxim_output_extracts_known_metrics():
    parsed = parse_noxim_output(
        """
        Average latency: 12.5
        Throughput = 0.91
        Power: 4.2
        Energy = 33.0
        """
    )
    assert parsed == {
        "average_latency": 12.5,
        "throughput": 0.91,
        "power": 4.2,
        "energy": 33.0,
    }
