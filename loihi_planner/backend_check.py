from __future__ import annotations

import os
from importlib import metadata
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MPL_CACHE = _PROJECT_ROOT / ".matplotlib-cache"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))


def _module_version(module_name: str, distribution_names: tuple[str, ...] = ()) -> str | None:
    try:
        module = __import__(module_name)
    except Exception:
        return None

    version = getattr(module, "__version__", None)
    if version:
        return str(version)
    for distribution_name in (module_name, *distribution_names):
        try:
            return str(metadata.version(distribution_name))
        except Exception:
            continue
    return None


def _import_first_available(module_names: tuple[str, ...]) -> tuple[str | None, Exception | None]:
    last_error: Exception | None = None
    for module_name in module_names:
        try:
            __import__(module_name)
            return module_name, None
        except Exception as exc:
            last_error = exc
    return None, last_error


def check_brian2loihi_available() -> dict:
    error_parts: list[str] = []

    brian2_version = _module_version("brian2")
    if brian2_version is None:
        try:
            __import__("brian2")
        except Exception as exc:  # pragma: no cover - import failure path
            error_parts.append(f"brian2 import failed: {exc}")

    brian2loihi_module, brian2loihi_error = _import_first_available(("brian2loihi", "brian2_loihi"))
    brian2loihi_version = None
    if brian2loihi_module is not None:
        brian2loihi_version = _module_version(
            brian2loihi_module,
            distribution_names=("brian2-loihi", "Brian2Loihi"),
        )
    else:
        error_parts.append(f"brian2loihi import failed: {brian2loihi_error}")

    available = brian2loihi_version is not None
    if available and brian2_version is None:
        available = False
        error_parts.append("brian2 is missing")

    error = None
    if not available:
        if error_parts:
            error = "; ".join(error_parts)
        else:
            error = "Brian2Loihi is not available in this environment."

    return {
        "available": available,
        "brian2_version": brian2_version,
        "brian2loihi_version": brian2loihi_version,
        "brian2loihi_module": brian2loihi_module,
        "error": error,
    }
