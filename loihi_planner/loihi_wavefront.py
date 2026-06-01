from __future__ import annotations

import networkx as nx
import numpy as np

from ._brian2_runner import load_brian2loihi_backend
from .backend_check import check_brian2loihi_available
from .wavefront_reference import event_driven_wavefront


def _build_sim_time_ms(G: nx.DiGraph, reference_arrival: float | None, delay_attr: str) -> int:
    delays = [int(attrs.get(delay_attr, 1)) for _, _, attrs in G.edges(data=True) if attrs.get("state") != "blocked"]
    max_delay = max(delays) if delays else 1
    path_bound = int((reference_arrival or 0.0) + max_delay + 5)
    graph_bound = int(max(5, len(G) * max_delay + 5))
    return max(path_bound, graph_bound)


def _format_error(
    prefix: str,
    error: str,
    start: int | None = None,
    target: int | None = None,
    sim_time_ms: int | None = None,
    backend: str = "unavailable",
) -> dict:
    return {
        "backend": backend,
        "start": start,
        "target": target,
        "spike_times_by_neuron": {},
        "target_arrival_time_ms": None,
        "num_spikes": 0,
        "active_neurons": 0,
        "sim_time_ms": sim_time_ms,
        "success": False,
        "error": f"{prefix}: {error}",
    }


def run_loihi_wavefront(
    G: nx.DiGraph,
    start: int,
    target: int,
    delay_attr: str = "delay_ms",
    sim_time_ms: int | None = None,
    threshold: float = 1.0,
    weight: float = 1.1,
    refractory_ms: int = 1000,
    seed: int = 0,
) -> dict:
    backend_check = check_brian2loihi_available()
    if not backend_check["available"]:
        return _format_error(
            "Brian2Loihi unavailable",
            backend_check["error"] or "unknown backend error",
            start=start,
            target=target,
        )

    backend, error = load_brian2loihi_backend()
    if error:
        return _format_error(
            "Brian2Loihi backend load failed",
            error,
            start=start,
            target=target,
        )

    if start not in G:
        return _format_error("Invalid start node", f"start node {start} not found", start=start, target=target)
    if target not in G:
        return _format_error("Invalid target node", f"target node {target} not found", start=start, target=target)

    try:
        reference = event_driven_wavefront(G, start, target, delay_attr=delay_attr)
    except Exception as exc:
        return _format_error("Reference wavefront failed", str(exc), start=start, target=target)

    try:
        b2 = backend.brian2
        computed_sim_time_ms = int(sim_time_ms) if sim_time_ms is not None else _build_sim_time_ms(
            G, reference.get("target_arrival_time"), delay_attr
        )

        if backend.mode == "object_api":
            loihi = backend.loihi_module
            b2.start_scope()
            nodes = list(G.nodes())
            node_index = {node: idx for idx, node in enumerate(nodes)}
            refractory_steps = max(1, min(64, int(refractory_ms)))
            neurons = loihi.LoihiNeuronGroup(
                len(nodes),
                refractory=refractory_steps,
                threshold_v_mant=max(1, int(round(float(threshold) * 64))),
                decay_v=0,
                decay_I=4096,
            )
            input_group = loihi.LoihiSpikeGeneratorGroup(
                1,
                np.array([0], dtype=int),
                np.array([0], dtype=int),
            )
            input_synapses = loihi.LoihiSynapses(input_group, neurons, delay=0)
            input_synapses.connect(i=np.array([0], dtype=int), j=np.array([node_index[start]], dtype=int))
            input_synapses.w = np.array([120], dtype=int)

            delay_groups: dict[int, list[tuple[int, int]]] = {}
            for source, target_node, attrs in G.edges(data=True):
                if attrs.get("state") == "blocked":
                    continue
                if source == target_node:
                    continue
                delay = int(attrs.get(delay_attr, 0))
                if delay <= 0:
                    continue
                adjusted_delay = max(0, delay - 1)
                delay_groups.setdefault(adjusted_delay, []).append((node_index[source], node_index[target_node]))

            synapse_objects = [input_synapses]
            for adjusted_delay, edges in sorted(delay_groups.items()):
                synapses = loihi.LoihiSynapses(neurons, neurons, delay=adjusted_delay)
                synapses.connect(
                    i=np.array([source for source, _ in edges], dtype=int),
                    j=np.array([target for _, target in edges], dtype=int),
                )
                synapses.w = np.array([120] * len(edges), dtype=int)
                synapse_objects.append(synapses)

            spike_monitor = loihi.LoihiSpikeMonitor(neurons)
            network = loihi.LoihiNetwork(*([input_group, neurons] + synapse_objects + [spike_monitor]))
            network.run(computed_sim_time_ms)

            spike_times_by_neuron: dict[int, float] = {}
            for neuron_index, spike_time in zip(spike_monitor.i, spike_monitor.t):
                node = nodes[int(neuron_index)]
                if node not in spike_times_by_neuron:
                    spike_times_by_neuron[node] = float(spike_time)

            target_arrival_time_ms = spike_times_by_neuron.get(target)
            success = target_arrival_time_ms is not None
            return {
                "backend": backend.name,
                "start": int(start),
                "target": int(target),
                "spike_times_by_neuron": spike_times_by_neuron,
                "target_arrival_time_ms": target_arrival_time_ms,
                "num_spikes": int(len(spike_monitor.t)),
                "active_neurons": int(len(spike_times_by_neuron)),
                "sim_time_ms": int(computed_sim_time_ms),
                "success": success,
                "error": None if success else f"Target neuron {target} did not spike.",
            }

        device_name = backend.device_name
        b2.set_device(device_name)
        b2.start_scope()
        if hasattr(b2, "seed"):
            try:
                b2.seed(seed)
            except Exception:
                pass
        b2.defaultclock.dt = 1 * b2.ms

        nodes = list(G.nodes())
        node_index = {node: idx for idx, node in enumerate(nodes)}

        neurons = b2.NeuronGroup(
            len(nodes),
            model="dv/dt = -v / (10*ms) : 1",
            threshold=f"v > {float(threshold)}",
            reset="v = 0",
            refractory=f"{int(refractory_ms)}*ms",
            method="euler",
        )
        neurons.v = 0.0

        input_group = b2.SpikeGeneratorGroup(
            1,
            np.array([0], dtype=int),
            np.array([0.0]) * b2.ms,
        )
        input_synapses = b2.Synapses(input_group, neurons, on_pre=f"v_post += {float(weight)}")
        input_synapses.connect(i=np.array([0], dtype=int), j=np.array([node_index[start]], dtype=int))

        sources: list[int] = []
        targets: list[int] = []
        delays: list[int] = []
        for source, target_node, attrs in G.edges(data=True):
            if attrs.get("state") == "blocked":
                continue
            if source == target_node:
                continue
            delay = int(attrs.get(delay_attr, 0))
            if delay <= 0:
                continue
            sources.append(node_index[source])
            targets.append(node_index[target_node])
            delays.append(delay)

        graph_synapses = b2.Synapses(neurons, neurons, on_pre=f"v_post += {float(weight)}")
        if sources:
            graph_synapses.connect(i=np.array(sources, dtype=int), j=np.array(targets, dtype=int))
            graph_synapses.delay = np.array(delays, dtype=float) * b2.ms

        spike_monitor = b2.SpikeMonitor(neurons)
        network = b2.Network(input_group, neurons, input_synapses, graph_synapses, spike_monitor)

        network.run(float(computed_sim_time_ms) * b2.ms)

        spike_times_by_neuron: dict[int, float] = {}
        for neuron_index, spike_time in zip(spike_monitor.i, spike_monitor.t):
            node = nodes[int(neuron_index)]
            if node not in spike_times_by_neuron:
                spike_times_by_neuron[node] = float(spike_time / b2.ms)

        target_arrival_time_ms = spike_times_by_neuron.get(target)
        success = target_arrival_time_ms is not None
        return {
            "backend": backend.name,
            "start": int(start),
            "target": int(target),
            "spike_times_by_neuron": spike_times_by_neuron,
            "target_arrival_time_ms": target_arrival_time_ms,
            "num_spikes": int(len(spike_monitor.t)),
            "active_neurons": int(len(spike_times_by_neuron)),
            "sim_time_ms": int(computed_sim_time_ms),
            "success": success,
            "error": None if success else f"Target neuron {target} did not spike.",
        }
    except Exception as exc:  # pragma: no cover - backend-dependent
        return {
            "backend": backend.name,
            "start": int(start),
            "target": int(target),
            "spike_times_by_neuron": {},
            "target_arrival_time_ms": None,
            "num_spikes": 0,
            "active_neurons": 0,
            "sim_time_ms": int(sim_time_ms) if sim_time_ms is not None else None,
            "success": False,
            "error": str(exc),
        }
