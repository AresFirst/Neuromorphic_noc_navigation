# 项目结构说明

本文档说明当前项目目录职责。当前开发重点是跑通 MoST/SUMO 城市道路地图的软件层导航，并保证最终可视化基于原始 SUMO 道路几何，而不是 NetworkX 点状图。

## 核心分层

```text
src/nmn/
├── dynamic/       # 动态拥塞、车辆状态、重规划闭环、动态可视化
├── graph/         # 新标准包占位；旧 graph/ 仍是主要实现
├── datasets/      # 新标准包占位；旧 dataset_import/ 仍是主要实现
├── loihi/         # Brian2Loihi 静态 wrapper：wavefront、parent trace、路径比较
├── localization/  # Grid cells、Place cells、动态起点估计兼容入口
├── noc/           # NoC 兼容入口；当前城市导航主线不依赖它
├── sumo/          # SUMO 原始几何解析、临时图转换、路径反映射、overlay 可视化
└── utils/         # 配置、路径、JSON、日志辅助函数
```

## 关键目录

- `src/nmn/sumo/`：当前 MoST/SUMO overlay 导航的核心。读取 `.net.xml` 的 lane shape，生成临时 `DiGraph`，并把 SNN 输出路径映射回 SUMO edge/lane/polyline。
- `src/nmn/sumo/dynamic.py`：随机背景车辆、交通密度统计、拥塞到 `delay_ms/state/threshold_penalty` 的映射、GIF 写出。
- `src/nmn/dynamic/`：graph-level 动态城市导航闭环，不接 CARLA，也不接 SUMO TraCI。
- `src/nmn/loihi/`：对 `loihi_planner/` 的静态 wrapper，解决 `nmn.loihi.*` 导入和 Pylance 解析问题。
- `dataset_import/`：旧导入实现，负责 MoST / SUMO `.net.xml` 到标准 `networkx.DiGraph` 的导入与标准化。
- `loihi_planner/`：Brian2Loihi 后端检测、demo、wavefront、parent trace、路径重建等成熟实现。
- `graph/`：synthetic graph、Dijkstra 基线、图 JSON 序列化、图指标和旧图可视化。
- `noc/`：NoC / Noxim 相关验证。当前城市道路软件层目标不需要运行它。
- `experiments/`：CLI 编排入口，只串联流程，不承载核心算法。
- `configs/`：实验配置。
- `tests/`：单元测试和集成测试。
- `docs/`：中文文档。
- `datasets/`：本地数据集目录。当前仓库中 MoST 示例位于 `datasets/MoSTScenario-master/`。
- `results/`：实验输出。

## 当前推荐入口

### MoST / SUMO 原始几何叠加导航

```text
configs/most_sumo_overlay.yaml
experiments/run_most_sumo_overlay_navigation.py
src/nmn/sumo/
```

用途：保持 SUMO 原始道路结构作为可视化底图，`DiGraph` 只作为 Brian2Loihi 规划的临时计算图。

主要输出：

```text
results/most_sumo_overlay/planning_summary.json
results/most_sumo_overlay/sumo_route.json
results/most_sumo_overlay/temporary_planning_graph.json
results/most_sumo_overlay/route_overlay.png
results/most_sumo_overlay/route_overlay_zoom.png
```

### 动态 SUMO 原始几何导航

```text
configs/dynamic_sumo_overlay.yaml
experiments/run_dynamic_sumo_overlay_navigation.py
src/nmn/sumo/dynamic.py
src/nmn/sumo/visualization.py
```

用途：在 SUMO 原始地图上显示随机车辆、拥塞道路、Brian2Loihi spike wavefront 和随交通变化重规划的路线。

主要输出：

```text
results/dynamic_sumo_overlay/dynamic_summary.json
results/dynamic_sumo_overlay/dynamic_step_logs.json
results/dynamic_sumo_overlay/latest_sumo_route.json
results/dynamic_sumo_overlay/dynamic_frames/
results/dynamic_sumo_overlay/wavefront_frames/
results/dynamic_sumo_overlay/dynamic_navigation.gif
results/dynamic_sumo_overlay/wavefront_all.gif
```

### MoST graph-level 导入与导航

```text
configs/most.yaml
experiments/run_most_import.py
experiments/run_most_navigation.py
```

用途：把 SUMO `.net.xml` 标准化成 `results/most/graph.json`，再在 graph-level 上跑路径规划和对比。

### 动态城市导航

```text
configs/dynamic_city_navigation.yaml
experiments/run_dynamic_city_navigation.py
src/nmn/dynamic/
```

用途：读取 `results/most/graph.json`，在拥塞事件影响下用 Brian2Loihi wavefront 做重规划闭环。

### 可选 NoC 验证

```text
configs/noxim.yaml
experiments/run_noc_validation.py
noc/
```

用途：将脉冲/路径相关数据映射到 NoC 交通表并可选调用本地 Noxim。它不是 MoST/SUMO 城市道路软件层导航的必要步骤。

## 设计原则

1. `src/nmn` 是新标准包入口。
2. 根目录旧包保留兼容，避免破坏已有脚本和测试。
3. `experiments/` 只做 CLI 编排。
4. MoST/SUMO 最终可视化必须使用原始 SUMO 几何，不用 NetworkX scatter 作为最终地图。
5. `DiGraph` 可以用于计算、SNN 编码和动态闭环，但不能替代 SUMO/MoST 原始显示层。
6. Brian2Loihi 是 Loihi 相关流程的强依赖；项目不会静默降级成普通 Brian2。
7. NoC/Noxim 是可选验证，不应阻塞城市道路导航主线。
