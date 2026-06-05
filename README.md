# neuromorphic_noc_navigation

这是一个面向复杂图与城市道路图的神经形态路径规划项目。项目把 `networkx.DiGraph` 映射为 Loihi 风格的脉冲神经网络，用 SNN wavefront 完成最短延迟路径传播，并支持 parent trace / STDP 回溯、动态起点、relay gate 和可选 NoC 验证。

## 核心流程

```text
Synthetic graph 或 MoST/SUMO 城市地图
    -> networkx.DiGraph 标准格式
    -> Brian2Loihi / Loihi-like SNN wavefront
    -> 脉冲时间表
    -> parent trace / STDP 路径回溯
    -> 路径对比与可视化
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
