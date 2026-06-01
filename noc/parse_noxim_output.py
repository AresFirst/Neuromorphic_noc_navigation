from __future__ import annotations

import json
import re
from pathlib import Path


_NUMBER_RE = r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"


def _extract_metric(text: str, labels: list[str]) -> float | None:
    for label in labels:
        pattern = re.compile(
            rf"{re.escape(label)}\s*[:=]\s*{_NUMBER_RE}",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def _with_legacy_aliases(parsed: dict) -> dict:
    parsed["average_latency"] = parsed.get("global_average_delay_cycles")
    parsed["throughput"] = parsed.get("network_throughput_flits_per_cycle")
    parsed["energy"] = parsed.get("total_energy_j")
    return parsed


def parse_noxim_output(stdout_text: str) -> dict:
    executed_cycles = None
    executed_match = re.search(
        r"Noxim simulation completed\.\s*\((\d+)\s+cycles executed\)",
        stdout_text,
        re.IGNORECASE,
    )
    if executed_match:
        try:
            executed_cycles = float(executed_match.group(1))
        except ValueError:
            executed_cycles = None

    parsed = {
        "executed_cycles": executed_cycles,
        "total_received_packets": _extract_metric(stdout_text, ["Total received packets"]),
        "total_received_flits": _extract_metric(stdout_text, ["Total received flits"]),
        "received_ideal_flits_ratio": _extract_metric(stdout_text, ["Received/Ideal flits Ratio"]),
        "average_wireless_utilization": _extract_metric(stdout_text, ["Average wireless utilization"]),
        "global_average_delay_cycles": _extract_metric(
            stdout_text,
            ["Global average delay (cycles)", "Average latency"],
        ),
        "max_delay_cycles": _extract_metric(stdout_text, ["Max delay (cycles)"]),
        "network_throughput_flits_per_cycle": _extract_metric(
            stdout_text,
            ["Network throughput (flits/cycle)", "Throughput"],
        ),
        "average_ip_throughput_flits_per_cycle_per_ip": _extract_metric(
            stdout_text,
            ["Average IP throughput (flits/cycle/IP)"],
        ),
        "total_energy_j": _extract_metric(stdout_text, ["Total energy (J)", "Energy"]),
        "dynamic_energy_j": _extract_metric(stdout_text, ["Dynamic energy (J)"]),
        "static_energy_j": _extract_metric(stdout_text, ["Static energy (J)"]),
        "power": _extract_metric(stdout_text, ["Power"]),
    }
    return _with_legacy_aliases(parsed)


def parse_noxim_stats_payload(payload: dict) -> dict:
    summary = payload.get("summary", payload)
    parsed = {
        "executed_cycles": summary.get("executed_cycles"),
        "total_received_packets": summary.get("total_received_packets"),
        "total_received_flits": summary.get("total_received_flits"),
        "received_ideal_flits_ratio": summary.get("received_ideal_flits_ratio"),
        "average_wireless_utilization": summary.get("average_wireless_utilization"),
        "global_average_delay_cycles": summary.get("global_average_delay_cycles"),
        "max_delay_cycles": summary.get("max_delay_cycles"),
        "network_throughput_flits_per_cycle": summary.get("network_throughput_flits_per_cycle"),
        "average_ip_throughput_flits_per_cycle_per_ip": summary.get(
            "average_ip_throughput_flits_per_cycle_per_ip"
        ),
        "total_energy_j": summary.get("total_energy_j"),
        "dynamic_energy_j": summary.get("dynamic_energy_j"),
        "static_energy_j": summary.get("static_energy_j"),
        "power": summary.get("power"),
    }
    return _with_legacy_aliases(parsed)


def parse_noxim_stats_file(path: str | Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_noxim_stats_payload(payload)
