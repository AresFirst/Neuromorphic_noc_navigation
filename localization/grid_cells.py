from __future__ import annotations

import math

import numpy as np


class GridCellEncoder:
    def __init__(
        self,
        wavelengths: list[float] | None = None,
        phases: list[float] | None = None,
    ):
        self.wavelengths = list(wavelengths or [0.2, 0.4, 0.8, 1.6])
        if any(value <= 0 for value in self.wavelengths):
            raise ValueError("wavelengths must be positive")
        self.phases = list(phases or [0.0, math.pi / 3.0, 2.0 * math.pi / 3.0])

    def encode(self, x: float, y: float) -> np.ndarray:
        values: list[float] = []
        for wavelength in self.wavelengths:
            scale = 2.0 * math.pi / wavelength
            for phase in self.phases:
                values.append(math.sin(scale * x + phase))
                values.append(math.cos(scale * x + phase))
                values.append(math.sin(scale * y + phase))
                values.append(math.cos(scale * y + phase))
                values.append(math.sin(scale * (x + y) / math.sqrt(2.0) + phase))
                values.append(math.cos(scale * (x + y) / math.sqrt(2.0) + phase))
        return np.asarray(values, dtype=float)
