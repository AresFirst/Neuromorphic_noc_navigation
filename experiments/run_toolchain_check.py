"""工具链检查入口。

这是 `run_week1_toolchain_check.py` 的兼容别名，保留更简洁的脚本名。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.run_week1_toolchain_check import main


if __name__ == "__main__":
    raise SystemExit(main())
