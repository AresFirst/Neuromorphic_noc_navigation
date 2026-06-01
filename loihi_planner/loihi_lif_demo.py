from __future__ import annotations

import numpy as np

from ._brian2_runner import load_brian2loihi_backend
from .backend_check import check_brian2loihi_available


def run_loihi_lif_demo() -> dict:
    backend_check = check_brian2loihi_available()
    if not backend_check["available"]:
        return {
            "backend": "unavailable",
            "num_spikes": 0,
            "spike_times_ms": [],
            "success": False,
            "error": backend_check["error"] or "Brian2Loihi is not available.",
        }

    backend, error = load_brian2loihi_backend()
    if error:
        return {
            "backend": "unavailable",
            "num_spikes": 0,
            "spike_times_ms": [],
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
                1,
                refractory=10,
                threshold_v_mant=100,
                decay_v=0,
                decay_I=4096,
            )
            synapses = loihi.LoihiSynapses(input_group, neurons, delay=0)
            synapses.connect(i=np.array([0], dtype=int), j=np.array([0], dtype=int))
            synapses.w = np.array([120], dtype=int)
            monitor = loihi.LoihiSpikeMonitor(neurons)
            network = loihi.LoihiNetwork(input_group, neurons, synapses, monitor)
            network.run(5)
            spike_times_ms = [float(time) for time in monitor.t]
            return {
                "backend": backend.name,
                "num_spikes": len(spike_times_ms),
                "spike_times_ms": spike_times_ms,
                "success": len(spike_times_ms) >= 1,
                "error": None if spike_times_ms else "The neuron did not spike.",
            }

        device_name = backend.device_name
        b2.set_device(device_name)
        b2.start_scope()
        b2.defaultclock.dt = 1 * b2.ms

        input_group = b2.SpikeGeneratorGroup(1, np.array([0], dtype=int), np.array([0.0]) * b2.ms)
        neurons = b2.NeuronGroup(
            1,
            model="dv/dt = -v / (10*ms) : 1",
            threshold="v > 1.0",
            reset="v = 0",
            method="euler",
        )
        neurons.v = 0.0
        synapses = b2.Synapses(input_group, neurons, on_pre="v_post += 1.1")
        synapses.connect()
        monitor = b2.SpikeMonitor(neurons)

        network = b2.Network(input_group, neurons, synapses, monitor)
        network.run(5 * b2.ms)

        spike_times_ms = [float(time / b2.ms) for time in monitor.t]
        return {
            "backend": device_name,
            "num_spikes": len(spike_times_ms),
            "spike_times_ms": spike_times_ms,
            "success": len(spike_times_ms) >= 1,
            "error": None if spike_times_ms else "The neuron did not spike.",
        }
    except Exception as exc:  # pragma: no cover - backend-dependent
        return {
            "backend": backend.name,
            "num_spikes": 0,
            "spike_times_ms": [],
            "success": False,
            "error": str(exc),
        }
