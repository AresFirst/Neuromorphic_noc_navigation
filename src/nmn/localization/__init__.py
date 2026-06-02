"""Grid/Place cells 与动态起点入口。"""

from __future__ import annotations

import sys
from importlib import import_module

from localization.dynamic_start import estimate_start_node_from_position
from localization.grid_cells import GridCellEncoder
from localization.place_cells import PlaceCellLayer

_ALIASES = {
    "dynamic_start": "localization.dynamic_start",
    "grid_cells": "localization.grid_cells",
    "place_cells": "localization.place_cells",
}

for name, module_name in _ALIASES.items():
    sys.modules[f"{__name__}.{name}"] = import_module(module_name)

__all__ = [
    "GridCellEncoder",
    "PlaceCellLayer",
    "estimate_start_node_from_position",
]
