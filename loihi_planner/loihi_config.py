from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Brian2LoihiRuntimeConfig:
    backend: str = "brian2loihi"
    dt_ms: int = 1
    threshold: float = 1.0
    weight: float = 1.1
    refractory_ms: int = 1000
    seed: int = 0


def load_brian2loihi_config(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    config = Brian2LoihiRuntimeConfig(
        backend=str(data.get("backend", "brian2loihi")),
        dt_ms=int(data.get("dt_ms", 1)),
        threshold=float(data.get("threshold", 1.0)),
        weight=float(data.get("weight", 1.1)),
        refractory_ms=int(data.get("refractory_ms", 1000)),
        seed=int(data.get("seed", 0)),
    )
    return asdict(config)


def normalize_wavefront_config(data: dict[str, Any] | None) -> dict[str, Any]:
    payload = data or {}
    return asdict(
        Brian2LoihiRuntimeConfig(
            backend=str(payload.get("backend", "brian2loihi")),
            dt_ms=int(payload.get("dt_ms", 1)),
            threshold=float(payload.get("threshold", 1.0)),
            weight=float(payload.get("weight", 1.1)),
            refractory_ms=int(payload.get("refractory_ms", 1000)),
            seed=int(payload.get("seed", 0)),
        )
    )
