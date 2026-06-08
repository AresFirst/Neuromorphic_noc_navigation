"""Streamlit entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
# 允许用户直接运行 `streamlit run app.py`，无需先执行 `pip install -e .`。
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# 正式 GUI 入口放在 src/gui/app.py；根目录 app.py 只负责路径准备和转发。
from gui.app import main


if __name__ == "__main__":
    # Streamlit 会执行本文件；main 内部负责页面布局、地图加载、SNN 导航和交通重规划。
    main()
