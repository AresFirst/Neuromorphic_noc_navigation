from __future__ import annotations

import re


def _extract_metric(text: str, label: str) -> float | None:
    pattern = re.compile(
        rf"{label}\s*[:=]\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def parse_noxim_output(stdout_text: str) -> dict:
    return {
        "average_latency": _extract_metric(stdout_text, "average latency"),
        "throughput": _extract_metric(stdout_text, "throughput"),
        "power": _extract_metric(stdout_text, "power"),
        "energy": _extract_metric(stdout_text, "energy"),
    }
