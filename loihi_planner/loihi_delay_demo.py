from __future__ import annotations

import numpy as np

from ._brian2_runner import load_brian2loihi_backend
from .backend_check import check_brian2loihi_available


def run_loihi_delay_demo(delay_ms: int = 5) -> dict:
    if delay_ms < 1:
        return {
            "pre_spike_times_ms": [],
            "post_spike_times_ms": [],
            "observed_delay_ms": None,
            "success": False,
            "error": "delay_ms must be a positive integer.",
        }

    backend_check = check_brian2loihi_available()
    if not backend_check["available"]:
        return {
            "pre_spike_times_ms": [],
            "post_spike_times_ms": [],
            "observed_delay_ms": None,
            "success": False,
            "error": backend_check["error"] or "Brian2Loihi is not available.",
        }

    backend, error = load_brian2loihi_backend()
    if error:
        return {
            "pre_spike_times_ms": [],
            "post_spike_times_ms": [],
            "observed_delay_ms": None,
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
                2,
                refractory=max(1, min(64, delay_ms + 5)),
                threshold_v_mant=100,
                decay_v=0,
                decay_I=4096,
            )
            input_synapses = loihi.LoihiSynapses(input_group, neurons, delay=0)
            input_synapses.connect(i=np.array([0], dtype=int), j=np.array([0], dtype=int))
            input_synapses.w = np.array([120], dtype=int)

            graph_synapses = loihi.LoihiSynapses(neurons, neurons, delay=max(0, int(delay_ms) - 1))
            graph_synapses.connect(i=np.array([0], dtype=int), j=np.array([1], dtype=int))
            graph_synapses.w = np.array([120], dtype=int)
            monitor = loihi.LoihiSpikeMonitor(neurons)

            network = loihi.LoihiNetwork(input_group, neurons, input_synapses, graph_synapses, monitor)
            network.run(delay_ms + 5)

            pre_spike_times_ms = [float(time) for index, time in zip(monitor.i, monitor.t) if int(index) == 0]
            post_spike_times_ms = [float(time) for index, time in zip(monitor.i, monitor.t) if int(index) == 1]
            observed_delay_ms = None
            if pre_spike_times_ms and post_spike_times_ms:
                observed_delay_ms = float(post_spike_times_ms[0] - pre_spike_times_ms[0])
            success = observed_delay_ms is not None and abs(observed_delay_ms - float(delay_ms)) <= 1.0
            return {
                "pre_spike_times_ms": pre_spike_times_ms,
                "post_spike_times_ms": post_spike_times_ms,
                "observed_delay_ms": observed_delay_ms,
                "success": success,
                "error": None if success else "Observed delay did not match the configured delay.",
            }

        device_name = backend.device_name
        b2.set_device(device_name)
        b2.start_scope()
        b2.defaultclock.dt = 1 * b2.ms

        neurons = b2.NeuronGroup(
            2,
            model="dv/dt = -v / (10*ms) : 1",
            threshold="v > 1.0",
            reset="v = 0",
            method="euler",
        )
        neurons.v = 0.0
        neurons.v[0] = 1.1
        synapses = b2.Synapses(neurons, neurons, on_pre="v_post += 1.1")
        synapses.connect(i=np.array([0], dtype=int), j=np.array([1], dtype=int))
        synapses.delay = float(delay_ms) * b2.ms
        monitor = b2.SpikeMonitor(neurons)

        network = b2.Network(neurons, synapses, monitor)
        network.run((delay_ms + 5) * b2.ms)

        pre_spike_times_ms = [float(time / b2.ms) for index, time in zip(monitor.i, monitor.t) if int(index) == 0]
        post_spike_times_ms = [float(time / b2.ms) for index, time in zip(monitor.i, monitor.t) if int(index) == 1]
        observed_delay_ms = None
        if pre_spike_times_ms and post_spike_times_ms:
            observed_delay_ms = float(post_spike_times_ms[0] - pre_spike_times_ms[0])

        success = observed_delay_ms is not None and abs(observed_delay_ms - float(delay_ms)) <= 1.0
        return {
            "pre_spike_times_ms": pre_spike_times_ms,
            "post_spike_times_ms": post_spike_times_ms,
            "observed_delay_ms": observed_delay_ms,
            "success": success,
            "error": None if success else "Observed delay did not match the configured delay.",
        }
    except Exception as exc:  # pragma: no cover - backend-dependent
        return {
            "pre_spike_times_ms": [],
            "post_spike_times_ms": [],
            "observed_delay_ms": None,
            "success": False,
            "error": str(exc),
        }
