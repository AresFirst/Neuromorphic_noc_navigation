"""轻量级 PEP 517/660 构建后端。

目的很单纯：
- 让 `pip install -e .` 在离线环境也能工作；
- 不依赖外部构建包下载；
- 只生成一个把仓库根目录和 `src/` 加入路径的 editable wheel。

这不是通用打包后端，只覆盖本项目需要的最小能力。
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

NAME = "neuromorphic-sumo-navigation"
VERSION = "0.1.0"
DIST_NAME = "neuromorphic_sumo_navigation"
WHEEL_TAG = "py3-none-any"
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
TOP_LEVEL_PACKAGES = ["loihi_planner", "nmn"]


def _dist_info_dir() -> str:
    return f"{DIST_NAME}-{VERSION}.dist-info"


def _wheel_name() -> str:
    return f"{DIST_NAME}-{VERSION}-{WHEEL_TAG}.whl"


def _metadata_text() -> str:
    return (
        "Metadata-Version: 2.1\n"
        f"Name: {NAME}\n"
        f"Version: {VERSION}\n"
        "Summary: SUMO/MoST city-road navigation with Brian2Loihi wavefront replanning\n"
    )


def _wheel_text() -> str:
    return (
        "Wheel-Version: 1.0\n"
        "Generator: build_backend\n"
        "Root-Is-Purelib: true\n"
        f"Tag: {WHEEL_TAG}\n"
    )


def _top_level_text() -> str:
    return "\n".join(TOP_LEVEL_PACKAGES) + "\n"


def get_requires_for_build_wheel(config_settings=None):  # noqa: D401
    return []


def get_requires_for_build_editable(config_settings=None):  # noqa: D401
    return []


def _metadata_bytes() -> dict[str, bytes]:
    dist_info = _dist_info_dir()
    return {
        f"{dist_info}/METADATA": _metadata_text().encode("utf-8"),
        f"{dist_info}/WHEEL": _wheel_text().encode("utf-8"),
        f"{dist_info}/top_level.txt": _top_level_text().encode("utf-8"),
        "neuromorphic_sumo_navigation.pth": (str(ROOT) + "\n" + str(SRC) + "\n").encode("utf-8"),
    }


def _record_bytes(payload: dict[str, bytes]) -> bytes:
    rows: list[list[str]] = []
    for path, data in payload.items():
        digest = hashlib.sha256(data).digest()
        encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        rows.append([path, f"sha256={encoded}", str(len(data))])
    rows.append([f"{_dist_info_dir()}/RECORD", "", ""])

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _build_wheel_file(wheel_directory: str | Path) -> str:
    wheel_directory = Path(wheel_directory)
    wheel_directory.mkdir(parents=True, exist_ok=True)
    wheel_path = wheel_directory / _wheel_name()

    payload = _metadata_bytes()
    payload[f"{_dist_info_dir()}/RECORD"] = _record_bytes(payload)

    with ZipFile(wheel_path, "w", compression=ZIP_DEFLATED) as zf:
        for path, data in payload.items():
            zf.writestr(path, data)
    return wheel_path.name


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):  # noqa: D401
    return _build_wheel_file(wheel_directory)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):  # noqa: D401
    return _build_wheel_file(wheel_directory)


def _write_metadata_dir(metadata_directory: str | Path) -> str:
    metadata_directory = Path(metadata_directory)
    dist_info = metadata_directory / _dist_info_dir()
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(_metadata_text(), encoding="utf-8")
    (dist_info / "WHEEL").write_text(_wheel_text(), encoding="utf-8")
    (dist_info / "top_level.txt").write_text(_top_level_text(), encoding="utf-8")
    return dist_info.name


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):  # noqa: D401
    return _write_metadata_dir(metadata_directory)


def prepare_metadata_for_build_editable(metadata_directory, config_settings=None):  # noqa: D401
    return _write_metadata_dir(metadata_directory)
