"""pytest 全局配置文件。

在测试运行前做两件事：
1. 将项目根目录加入 sys.path，确保 from loihi_planner... 等导入在测试中可用
2. 设置 matplotlib 缓存目录为项目内的 .matplotlib-cache/，
   避免在 CI/容器环境中写用户主目录导致的权限问题
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 将项目根目录添加到 Python 搜索路径
# 这样测试文件可以直接 import 项目模块，无需 pip install
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 设置 matplotlib 配置目录为项目本地路径
# 避免在无头环境 / CI / 受限容器中写 ~/.matplotlib 失败
MPL_CACHE = ROOT / ".matplotlib-cache"
MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPL_CACHE))
