# neuromorphic_noc_navigation

这是一个面向复杂图与城市道路图的神经形态路径规划项目。当前主线是 MoST/SUMO 城市道路地图的软件层导航：保留原始 SUMO 道路几何用于最终显示，临时使用 `networkx.DiGraph` 做计算和 SNN 编码，再用 Brian2Loihi wavefront 完成最短延迟路径传播。项目也支持 parent trace / STDP 回溯、动态起点、relay gate、动态拥塞重规划和可选 NoC 验证。

## 核心流程

```text
MoST / SUMO net.xml 或 synthetic graph
    -> 保留原始 SUMO geometry（城市地图显示层）
    -> 临时 networkx.DiGraph（计算层）
    -> Brian2Loihi / Loihi-like SNN wavefront
    -> parent trace / STDP 路径回溯
    -> SUMO edge/lane/polyline 反映射或 graph-level 路径对比
    -> 原始 SUMO geometry overlay / 动态可视化
    -> 可选 NoC / Noxim 验证
```

## 安装

```bash
pip install -e .
python -m pip install -r requirements.txt
```

Brian2Loihi 需要在当前 Python 环境中可导入。项目不会把 Brian2Loihi 静默替换成普通 Brian2；如果后端不可用，相关脚本会返回明确错误或 skipped 状态。

## 测试

```bash
pytest
```

也可以使用脚本：

```bash
bash scripts/run_tests.sh
```

## 常用命令

### 工具链检查

```bash
python experiments/run_toolchain_check.py
```

旧入口仍保留：

```bash
python experiments/run_week1_toolchain_check.py
```

### 生成 synthetic graph 并运行 Dijkstra 基线

```bash
python experiments/run_graph_baseline.py --config configs/graph.yaml --output results/week2
```

### 运行 Brian2Loihi wavefront

```bash
python experiments/run_loihi_wavefront.py \
  --graph results/week2/graph.json \
  --config configs/brian2loihi.yaml \
  --output results/week3 \
  --num-pairs 10 \
  --seed 0
```

### 运行 STDP / parent trace 路径重建

```bash
python experiments/run_stdp_path_reconstruction.py \
  --graph results/week2/graph.json \
  --config configs/brian2loihi.yaml \
  --output results/week4 \
  --num-pairs 20 \
  --seed 0
```

### 运行动态起点与 relay gate

```bash
python experiments/run_dynamic_start_and_relay.py \
  --graph results/week2/graph.json \
  --config configs/brian2loihi.yaml \
  --output results/week5 \
  --seed 0
```

## MoST 城市地图

MoST 是 Monaco SUMO Traffic Scenario。项目只实现本地导入逻辑，不自动联网下载地图。

推荐本地路径：

```bash
git clone https://github.com/lcodeca/MoSTScenario.git data/datasets/MoSTScenario
```

当前仓库示例数据也可能位于：

```text
datasets/MoSTScenario-master/
```

`configs/most_sumo_overlay.yaml` 默认使用 `datasets/MoSTScenario-master`，`configs/most.yaml` 默认使用 `data/datasets/MoSTScenario`。如果你的本地数据只在其中一个位置，请同步修改配置。

导入 MoST / SUMO `.net.xml`：

```bash
python experiments/run_most_import.py --config configs/most.yaml
```

导入后会生成：

```text
results/most/graph.json
results/most/graph_metrics.json
results/most/preview.png
results/most/import_summary.json
```

### MoST / SUMO 原始几何叠加导航

这个入口用于跑通“MoST 地图 -> 临时 DiGraph -> Brian2Loihi -> SUMO 道路轨迹 -> 原始地图 overlay”的软件层闭环。这里的 `networkx.DiGraph` 只作为 SNN 规划的中间计算表示，最终可视化始终使用 SUMO `.net.xml` 中的 lane shape / edge geometry，不输出 NetworkX 点线图作为最终地图。

推荐数据流：

```text
MoST / SUMO net.xml
    -> 临时 networkx.DiGraph（仅用于计算）
    -> SNN delay 编码
    -> Brian2Loihi wavefront
    -> parent trace 路径回溯
    -> SUMO edge id / lane id / polyline 反映射
    -> 原始 SUMO 几何 route overlay
```

目录与关键文件：

```text
src/nmn/sumo/geometry.py        # 读取 SUMO net.xml，保留 junction、edge、lane shape
src/nmn/sumo/conversion.py      # most_to_digraph / digraph_to_snn / snn_output_to_path / path_to_sumo_route
src/nmn/sumo/visualization.py   # 基于原始 SUMO 几何绘制 route overlay
src/nmn/sumo/sumo_check.py      # SUMO CLI 与地图加载检查
configs/most_sumo_overlay.yaml  # MoST + SUMO overlay 导航配置
experiments/run_most_sumo_overlay_navigation.py
```

SUMO 安装与检查：

```bash
# macOS 推荐先按官方文档安装 Eclipse SUMO 的 macOS package：
# https://eclipse.dev/sumo/docs/Installing/index.html

# 如果使用 Homebrew，需要先启用 DLR SUMO tap；默认 homebrew/core 没有 sumo：
brew tap dlr-ts/sumo
brew install sumo

# 也可以在 Brian2Loihi 环境中安装官方 Python wheel：
/opt/anaconda3/envs/brian2loihi/bin/python -m pip install eclipse-sumo

# 如果 sumo 不在 PATH，显式指定：
export SUMO_HOME=/path/to/eclipse-sumo
export SUMO_BINARY="$SUMO_HOME/bin/sumo"
export SUMO_GUI_BINARY="$SUMO_HOME/bin/sumo-gui"

sumo --version
sumo-gui datasets/MoSTScenario-master/scenario/most.sumocfg
```

注意：不要把 conda-forge 上名为 `sumo` 的材料科学工具包当成 Eclipse SUMO。项目的 `check_sumo_available()` 会调用 `sumo --version` 并在检测到同名错误命令时返回明确错误。

如果 `eclipse-sumo` wheel 在 macOS 上因为 bundled dylib 签名被系统拒绝，`sumolib/traci` 仍可能可导入，但 `sumo`/`sumo-gui` 无法运行；这时应改用官方 macOS package、Homebrew tap 或源码安装得到可执行的 SUMO CLI。

运行完整 overlay 导航：

```bash
python experiments/run_most_sumo_overlay_navigation.py \
  --config configs/most_sumo_overlay.yaml
```

如果当前机器的 SUMO 二进制暂时不可运行，但需要先验证 Python 软件链路，可以显式跳过 headless SUMO 加载检查：

```bash
python experiments/run_most_sumo_overlay_navigation.py \
  --config configs/most_sumo_overlay.yaml \
  --skip-sumo-load-check
```

输出文件：

```text
results/most_sumo_overlay/planning_summary.json
results/most_sumo_overlay/sumo_route.json
results/most_sumo_overlay/temporary_planning_graph.json
results/most_sumo_overlay/route_overlay.png
results/most_sumo_overlay/route_overlay_zoom.png
```

验证重点：

- `planning_summary.json` 中 `graph_is_temporary=true`，`visualization_source=original_sumo_geometry`；
- `sumo_route.json` 保存 `sumo_edge_ids`、`sumo_node_ids`、`lane_ids` 和每段 polyline；
- `route_overlay.png` 是完整地图上的 SUMO lane geometry 路径叠加，不是 NetworkX scatter/节点图；
- `route_overlay_zoom.png` 是路线附近的道路结构放大图；
- 若 `require_sumo_load_check=true`，脚本会先用 headless `sumo` 加载 `.sumocfg` 或 `.net.xml`，失败时直接中止。

## 软件闭环导航

不使用 Noxim，只验证城市地图到 SNN wavefront 的闭环：

```bash
python experiments/run_most_navigation.py \
  --config configs/most.yaml \
  --loihi-config configs/brian2loihi.yaml \
  --output results/most/navigation \
  --num-pairs 3 \
  --seed 0
```

输出中包含完整地图路径可视化：

```text
results/most/navigation/navigation_path_compare.png
```

## Dynamic City Navigation Demo

这个 demo 用 `networkx.DiGraph` 跑一个城市道路级别的动态闭环导航，不接 CARLA，也不接 SUMO TraCI。

它会读取 MoST 导出的 `graph.json`，用 Brian2Loihi wavefront 做初始和重规划；当道路拥塞时，边的 `delay_ms` 会增大，`state` 会切到 `congested` 或 `blocked`，可选的 `threshold_penalty` 也会被保留。

运行方式：

```bash
python experiments/run_most_import.py --config configs/most.yaml

python experiments/run_dynamic_city_navigation.py \
  --config configs/dynamic_city_navigation.yaml
```

输出文件：

```text
results/dynamic_city_navigation/dynamic_step_logs.csv
results/dynamic_city_navigation/dynamic_summary.json
results/dynamic_city_navigation/congestion_events.json
results/dynamic_city_navigation/final_route.json
results/dynamic_city_navigation/frames/
results/dynamic_city_navigation/preview_final.png
```

限制：

- 这是 graph-level 的动态导航，不是真实车辆动力学；
- 没有使用 SUMO TraCI；
- “实时”指仿真闭环，不是硬实时；
- Brian2Loihi 大图可能较慢，建议先用 `max_nodes=500~2000` 的 MoST 子图；
- 当前主要通过 synaptic `delay_ms` 表达拥塞，`threshold_penalty` 只作为保留字段。

## 可选 NoC 验证

NoC / Noxim 验证不是软件闭环导航的必要步骤。需要本地 Noxim 可用时再运行：

```bash
python experiments/run_noc_validation.py \
  --graph results/week2/graph.json \
  --loihi-config configs/brian2loihi.yaml \
  --noc-config configs/noxim.yaml \
  --output results/week6 \
  --num-pairs 20 \
  --seed 0
```

如果 Noxim 路径不可用，Python 实验仍会完成，并把 `noxim_status` 标记为 `skipped`。

## 新包结构

新标准包入口是：

```text
src/nmn/
```

根目录旧包仍作为兼容入口保留，避免破坏已有脚本和测试。后续新增代码建议优先使用 `nmn.*` 命名空间。

## 文档

- [项目结构说明](docs/project_structure.md)
- [数据格式说明](docs/data_format.md)
- [运行手册](docs/runbook.md)
- [重构审计报告](docs/refactor_audit.md)
- [Loihi demo 详解](docs/loihi_planner_demos.md)
- [项目解析](PROJECT_GUIDE.md)
