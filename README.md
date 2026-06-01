# neuromorphic_noc_navigation

Project scaffold for complex-graph navigation with a Loihi-style SNN path planner and NoC trace tooling.

## Goal

This project now covers toolchain validation, non-grid complex graph generation, a Dijkstra baseline, a Loihi-like wavefront reference, and STDP-style parent trace reconstruction. The NoC validation loop is still incomplete.

## Why these tools

- NetworkX for complex directed graph generation and graph algorithms.
- Brian2Loihi for Loihi-style spiking-network experimentation.
- Noxim for future NoC traffic and architecture validation.

## Install

```bash
python -m pip install -r requirements.txt
```

Brian2Loihi is handled separately if it is not already available in your environment.

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

## Current limits

- Dynamic start/relay handling and NoC packet trace generation are not implemented yet.
- Noxim absent in the environment returns `skipped` only.
