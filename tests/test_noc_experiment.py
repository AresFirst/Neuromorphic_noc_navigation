from pathlib import Path

import pytest

from loihi_planner.backend_check import check_brian2loihi_available
from noc.noc_experiment import run_single_noc_validation
from tests.test_wavefront_reference import _build_small_wavefront_graph


NOXIM_ROOT = Path("/Users/ares/code/noxim-master")
NOXIM_BIN = NOXIM_ROOT / "bin/noxim"
NOXIM_CONFIG = NOXIM_ROOT / "config_examples/default_configMeshNoHUB.yaml"
NOXIM_POWER = NOXIM_ROOT / "bin/power.yaml"


def test_run_single_noc_validation_completes_on_small_graph(tmp_path):
    status = check_brian2loihi_available()
    if not status["available"]:
        pytest.skip(f"Brian2Loihi unavailable: {status['error']}")

    graph = _build_small_wavefront_graph()
    result = run_single_noc_validation(
        graph,
        start=0,
        target=4,
        mesh_rows=2,
        mesh_cols=3,
        mapping_strategy="topology",
        output_dir=str(tmp_path),
        loihi_config={"noxim_bin": None, "noxim_config_path": None},
        seed=0,
    )

    assert result["success"]
    assert result["metrics"]["num_packets"] >= 3
    assert result["noxim_result"]["status"] == "skipped"


@pytest.mark.skipif(
    not (NOXIM_BIN.exists() and NOXIM_CONFIG.exists() and NOXIM_POWER.exists()),
    reason="Local Noxim installation not available",
)
def test_run_single_noc_validation_completes_with_real_noxim(tmp_path):
    status = check_brian2loihi_available()
    if not status["available"]:
        pytest.skip(f"Brian2Loihi unavailable: {status['error']}")

    graph = _build_small_wavefront_graph()
    result = run_single_noc_validation(
        graph,
        start=0,
        target=4,
        mesh_rows=2,
        mesh_cols=3,
        mapping_strategy="topology",
        output_dir=str(tmp_path),
        loihi_config={
            "noxim_bin": str(NOXIM_BIN),
            "noxim_config_path": str(NOXIM_CONFIG),
            "noxim_power_path": str(NOXIM_POWER),
            "noxim_packet_size": 2,
            "noxim_warmup_cycles": 0,
            "noxim_simulation_margin_cycles": 40,
        },
        seed=0,
    )

    assert result["success"]
    assert result["noxim_result"]["status"] == "ok"
    assert result["noxim_result"]["stats_path"] is not None
    assert result["noxim_result"]["parsed"]["total_received_packets"] >= 1
