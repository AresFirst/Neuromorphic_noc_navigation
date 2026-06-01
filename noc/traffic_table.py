from __future__ import annotations

from pathlib import Path


def save_sample_noxim_traffic_table(path: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# src_x src_y dst_x dst_y packet_size injection_time",
        "0 0 1 1 8 0",
        "1 1 2 2 8 4",
        "2 2 3 3 8 8",
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
