"""PySide6 desktop entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
# 允许用户直接运行 `python desktop_app.py`，无需先执行 `pip install -e .`。
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.desktop_viewer import main


if __name__ == "__main__":
    raise SystemExit(main())
