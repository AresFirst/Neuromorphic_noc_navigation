# neuromorphic_noc_navigation

Project scaffold for complex-graph navigation with a Loihi-style SNN path planner and NoC trace tooling.

## Goal

This project now covers toolchain validation, non-grid complex graph generation, a Dijkstra baseline, a Loihi-like wavefront reference, STDP-style parent trace reconstruction, dynamic start/relay replanning, and a real Noxim validation loop.

## Why these tools

- NetworkX for complex directed graph generation and graph algorithms.
- Brian2Loihi for Loihi-style spiking-network experimentation.
- Noxim for future NoC traffic and architecture validation.

## Install

```bash
python -m pip install -r requirements.txt
```

Brian2Loihi is handled separately if it is not already available in your environment.
For NoC validation, the project defaults to the local Noxim checkout at
`~/code/noxim-master` when present.

## Check Brian2Loihi

```bash
python - <<'PY'
from loihi_planner.backend_check import check_brian2loihi_available
print(check_brian2loihi_available())
PY
```

If Brian2Loihi is missing, the check returns `available: false` and an explicit import error.

## Run week 1 toolchain check

```bash
python experiments/run_week1_toolchain_check.py
```

This writes outputs under `results/week1/`.

## Run week 2 graph baseline

```bash
python experiments/run_graph_baseline.py --config configs/graph.yaml --output results/week2
```

This writes:

- `graph.json`
- `graph_metrics.json`
- `dijkstra_results.csv`
- `example_path.png`
- `summary.json`

## Week 3: Brian2Loihi Wavefront

```bash
python experiments/run_loihi_wavefront.py \
  --graph results/week2/graph.json \
  --config configs/brian2loihi.yaml \
  --output results/week3 \
  --num-pairs 10 \
  --seed 0
```

- Each graph node maps to one Loihi-like neuron.
- Each directed edge maps to a synapse with integer millisecond delay.
- Delays are integers because the Loihi-like event model here is discrete time.
- If Brian2Loihi is unavailable, the script records the error and does not fake a Loihi result.

## Week 4: STDP Parent Trace and Path Reconstruction

```bash
python experiments/run_stdp_path_reconstruction.py \
  --graph results/week2/graph.json \
  --config configs/brian2loihi.yaml \
  --output results/week4 \
  --num-pairs 50 \
  --seed 0
```

- STDP in this project means winner-take-all parent selection from the earliest valid predecessor.
- Parent traces are recovered from spike timing and edge delays.
- The recovered SNN path is compared against a Dijkstra baseline on the same delay weights.
- If Brian2Loihi is unavailable, the script writes explicit errors and leaves the Loihi trace empty.

## Week 5: Grid/Place Dynamic Start and Relay Gate

```bash
python experiments/run_dynamic_start_and_relay.py \
  --graph results/week2/graph.json \
  --config configs/brian2loihi.yaml \
  --output results/week5 \
  --seed 0
```

- Grid cells provide deterministic multi-scale periodic encodings of continuous `(x, y)` positions.
- Place cells compare a continuous position against graph node coordinates and choose the winner as the dynamic start node.
- Relay gate control changes graph edge state before replanning.
- `blocked` edges are skipped by wavefront propagation.
- `penalized` edges keep connectivity but increase `delay_ms` from `original_delay_ms`.

## Week 6: NoC Validation with Noxim

```bash
python experiments/run_noc_validation.py \
  --graph results/week2/graph.json \
  --loihi-config configs/brian2loihi.yaml \
  --noc-config configs/noxim.yaml \
  --output results/week6 \
  --num-pairs 20 \
  --seed 0
```

- Neurons map to NoC cores with three strategies:
  - `random`: seed-controlled random core assignment.
  - `community`: nodes in the same `region` are placed near each other.
  - `topology`: node `(x, y)` coordinates are projected to nearby mesh tiles.
- Spike traces become a Noxim `hardcoded` traffic file when `spike_time[u] + delay(u, v)` matches `spike_time[v]`.
- Packet trace columns are `cycle, src_neuron, dst_neuron, src_core, dst_core, packet_type, packet_size`.
- Proxy metrics include packet count, average/max/total Manhattan hop, energy proxy, and hotspot core count.
- The traffic table is still emitted as an approximate Noxim-readable aggregate over `(src_core, dst_core)` for inspection.
- The wrapper runs the local Noxim binary with `-config`, `-power`, `-traffic hardcoded`, and JSON stats export.
- If the binary path is missing, `noxim_status` is `skipped` and the Python experiment still completes.
- `configs/noxim.yaml` points at the mesh-only `default_configMeshNoHUB.yaml` from the official Noxim tree.

## Current limits

- The Noxim traffic table format is approximate and kept mainly for readability.
- Mesh validation expects the mesh-only `default_configMeshNoHUB.yaml` from the official Noxim tree.
