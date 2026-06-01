from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MPL_CACHE = _PROJECT_ROOT / ".matplotlib-cache"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))


@dataclass(frozen=True)
class Brian2LoihiBackend:
    brian2: Any
    loihi_module: Any
    name: str
    mode: str
    device_name: str | None = None


def _import_brian2loihi_module() -> tuple[Any | None, str | None, str | None]:
    errors: list[str] = []
    for module_name in ("brian2loihi", "brian2_loihi"):
        try:
            module = __import__(module_name)
            return module, module_name, None
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
    return None, None, "; ".join(errors)


def load_brian2loihi_backend() -> tuple[Brian2LoihiBackend | None, str | None]:
    try:
        import brian2 as b2
    except Exception as exc:
        return None, f"brian2 import failed: {exc}"

    loihi_module, module_name, import_error = _import_brian2loihi_module()
    if import_error:
        return None, f"brian2loihi import failed: {import_error}"

    try:
        b2.prefs.codegen.target = "numpy"
    except Exception:
        pass

    try:
        from brian2.devices.device import all_devices
    except Exception as exc:
        all_devices = {}

    device_name: str | None = None
    for candidate in ("brian2loihi", "loihi"):
        if candidate in all_devices:
            device_name = candidate
            break

    if device_name is not None:
        return Brian2LoihiBackend(
            brian2=b2,
            loihi_module=loihi_module,
            name=module_name or device_name,
            mode="brian2_device",
            device_name=device_name,
        ), None

    if hasattr(loihi_module, "LoihiNetwork"):
        return Brian2LoihiBackend(
            brian2=b2,
            loihi_module=loihi_module,
            name=module_name or "brian2_loihi",
            mode="object_api",
        ), None

    return None, "Brian2Loihi imported, but no supported backend API was found."
