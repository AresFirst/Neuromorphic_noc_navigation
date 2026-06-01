from __future__ import annotations

import numpy as np

from ._brian2_runner import load_brian2loihi_backend
from .backend_check import check_brian2loihi_available


def run_loihi_small_wavefront_demo() -> dict:
    backend_check = check_brian2loihi_available()
    if not backend_check["available"]:
        return {
            "spike_times_by_neuron": {},
            "target_arrival_time_ms": None,
            "success": False,
            "error": backend_check["error"] or "Brian2Loihi is not available.",
        }

    backend, error = load_brian2loihi_backend()
    if error:
        return {
            "spike_times_by_neuron": {},
            "target_arrival_time_ms": None,
            "success": False,
            "error": error,
        }

    try:
        b2 = backend.brian2
        if backend.mode == "object_api":
            loihi = backend.loihi_module
            b2.start_scope()
            input_group = loihi.LoihiSpikeGeneratorGroup(
                1,
                np.array([0], dtype=int),
                np.array([0], dtype=int),
            )
            neurons = loihi.LoihiNeuronGroup(
                5,
                refractory=20,
                threshold_v_mant=100,
                decay_v=0,
                decay_I=4096,
            )
            input_synapses = loihi.LoihiSynapses(input_group, neurons, delay=0)
            input_synapses.connect(i=np.array([0], dtype=int), j=np.array([0], dtype=int))
            input_synapses.w = np.array([120], dtype=int)

            synapse_objects = [input_synapses]
            edges_by_delay: dict[int, list[tuple[int, int]]] = {
                1: [(0, 1), (1, 3), (2, 3), (3, 4)],
                3: [(0, 2)],
            }
            for delay_ms, edges in edges_by_delay.items():
                synapses = loihi.LoihiSynapses(neurons, neurons, delay=max(0, delay_ms - 1))
                synapses.connect(
                    i=np.array([source for source, _target in edges], dtype=int),
                    j=np.array([target for _source, target in edges], dtype=int),
                )
                synapses.w = np.array([120] * len(edges), dtype=int)
                synapse_objects.append(synapses)

            monitor = loihi.LoihiSpikeMonitor(neurons)
            network = loihi.LoihiNetwork(input_group, neurons, *synapse_objects, monitor)
            network.run(8)

            spike_times_by_neuron: dict[int, list[float]] = {idx: [] for idx in range(5)}
            for index, time in zip(monitor.i, monitor.t):
                spike_times_by_neuron[int(index)].append(float(time))
            target_spikes = spike_times_by_neuron[4]
            target_arrival_time_ms = target_spikes[0] if target_spikes else None
            success = target_arrival_time_ms is not None and abs(target_arrival_time_ms - 3.0) <= 1.0
            return {
                "spike_times_by_neuron": spike_times_by_neuron,
                "target_arrival_time_ms": target_arrival_time_ms,
                "success": success,
                "error": None if success else "Target spike did not arrive near the expected time.",
            }

        device_name = backend.device_name
        b2.set_device(device_name)
        b2.start_scope()
        b2.defaultclock.dt = 1 * b2.ms

        neurons = b2.NeuronGroup(
            5,
            model="dv/dt = -v / (10*ms) : 1",
            threshold="v > 1.0",
            reset="v = 0",
            method="euler",
        )
        neurons.v = 0.0
        neurons.v[0] = 1.1

        synapses = b2.Synapses(neurons, neurons, on_pre="v_post += 1.1")
        sources = np.array([0, 0, 1, 2, 3], dtype=int)
        targets = np.array([1, 2, 3, 3, 4], dtype=int)
        synapses.connect(i=sources, j=targets)
        synapses.delay = np.array([1, 3, 1, 1, 1], dtype=float) * b2.ms
        monitor = b2.SpikeMonitor(neurons)

        network = b2.Network(neurons, synapses, monitor)
        network.run(8 * b2.ms)

        spike_times_by_neuron: dict[int, list[float]] = {idx: [] for idx in range(5)}
        for index, time in zip(monitor.i, monitor.t):
            spike_times_by_neuron[int(index)].append(float(time / b2.ms))

        target_spikes = spike_times_by_neuron[4]
        target_arrival_time_ms = target_spikes[0] if target_spikes else None
        success = target_arrival_time_ms is not None and abs(target_arrival_time_ms - 3.0) <= 1.0
        return {
            "spike_times_by_neuron": spike_times_by_neuron,
            "target_arrival_time_ms": target_arrival_time_ms,
            "success": success,
            "error": None if success else "Target spike did not arrive near the expected time.",
        }
    except Exception as exc:  # pragma: no cover - backend-dependent
        return {
            "spike_times_by_neuron": {},
            "target_arrival_time_ms": None,
            "success": False,
            "error": str(exc),
        }
