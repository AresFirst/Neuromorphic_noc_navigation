# 神经形态 NoC 导航项目解析

## 一、项目总览

本项目探索**用脉冲神经网络（SNN）在 NoC（Network-on-Chip，片上网络）上做路由规划**。核心思路是把图上的节点映射为 Loihi 风格的 LIF 神经元，图的边映射为带延迟的突触，用脉冲波前（wavefront）传播来找到最短路径。

**关键实验假设**：脉冲到达时间 = 路径代价。波前从起点出发，经过不同延迟的突触传播到各节点。目标节点最先接收到脉冲的时刻，代表了起点到目标的最短路径延迟。通过合理的 STDP 规则和 parent-trace 反向追踪，就能重建出实际路径。

**项目仓库地址**：`/Users/ares/code/neuromorphic_noc_navigation`

---

## 二、目录结构总览

```
neuromorphic_noc_navigation/
├── README.md                          # 项目说明（四周实验计划）
├── requirements.txt                   # Python 依赖
├── conftest.py                        # pytest 全局配置
│
├── configs/                           # ☆ 实验参数配置（YAML）
│   ├── graph.yaml                     #   图生成参数
│   ├── brian2loihi.yaml               #   SNN 模拟参数
│   └── noxim.yaml                     #   外部 NoC 模拟器参数
│
├── graph/                             # ☆ 图生成、传统算法、可视化
│   ├── __init__.py                    #   包导出
│   ├── complex_graph_generator.py     #   生成 4 种复杂拓扑图
│   ├── graph_baseline.py              #   Dijkstra 最短路径（传统基线）
│   ├── graph_io.py                    #   图的 JSON 序列化/反序列化
│   ├── graph_metrics.py               #   图结构统计（度、密度、延迟分布）
│   └── visualization.py              #   Matplotlib 图可视化
│
├── localization/                      # ☆ 动态起点定位模块
│   ├── grid_cells.py                  #   Grid cell 连续坐标编码
│   ├── place_cells.py                 #   Place cell 位置匹配
│   └── dynamic_start.py               #   连续位置到图节点的估计
│
├── loihi_planner/                     # ☆ 神经形态规划器核心
│   ├── __init__.py                    #   包导出（懒加载机制）
│   ├── _brian2_runner.py             #   Brian2/Brian2Loihi 后端加载
│   ├── backend_check.py              #   后端可用性检测
│   ├── loihi_config.py               #   运行时配置加载/规范化
│   ├── loihi_lif_demo.py             #   单神经元 LIF 验证 demo
│   ├── loihi_delay_demo.py           #   突触延迟验证 demo
│   ├── loihi_small_wavefront_demo.py #   小图波前传播验证 demo
│   ├── loihi_wavefront.py            #   ☆ 核心：Loihi SNN 波前路由
│   ├── wavefront_reference.py        #   CPU 参考波前算法（真值）
│   ├── spike_trace.py                #   脉冲时间序列的 CSV 读写
│   ├── parent_trace.py               #   从脉冲时间推断父节点关系
│   ├── path_reconstruction.py        #   从父关系反向追踪出完整路径
│   ├── path_compare.py               #   SNN 路径 vs Dijkstra 路径对比
│   └── stdp_trace.py                 #   构建 STDP 权重变化表
│
├── noc/                               # ☆ NoC 外部模拟器接口
│   ├── __init__.py
│   ├── mapping.py                     #   神经元到 NoC core 映射
│   ├── noc_experiment.py              #   单次 NoC 验证流程
│   ├── noc_proxy_metrics.py           #   NoC hop/energy proxy 指标
│   ├── noxim_wrapper.py              #   Noxim 子进程调用封装
│   ├── packet_trace.py                #   Spike trace → packet trace
│   ├── traffic_table.py               #   生成样例流量表与 hardcoded 文件
│   └── parse_noxim_output.py          #   解析 Noxim 输出指标
│
├── experiments/                       # ☆ 实验入口脚本
│   ├── run_week1_toolchain_check.py   #   Week1: 工具链可用性检查
│   ├── run_graph_baseline.py          #   Week2: Dijkstra 基线实验
│   ├── run_loihi_wavefront.py         #   Week3: Loihi 波前实验
│   ├── run_stdp_path_reconstruction.py # Week4: STDP 路径重建实验
│   ├── run_dynamic_start_and_relay.py  #   Week5: 动态起点与 relay 重规划
│   └── run_noc_validation.py          #   Week6: NoC 验证
│
├── tests/                             # 单元测试
│   ├── test_backend_check.py
│   ├── test_complex_graph_generator.py
│   ├── test_graph_baseline.py
│   ├── test_graph_io.py
│   ├── test_loihi_demos.py
│   ├── test_loihi_wavefront.py
│   ├── test_noc_utils.py
│   ├── test_parent_trace.py
│   ├── test_path_reconstruction.py
│   ├── test_spike_trace.py
│   ├── test_stdp_trace_compare.py
│   └── test_wavefront_reference.py
│
├── scripts/
│   └── run_tests.sh                   # 运行全部测试
│
└── results/                           # 实验结果输出
    ├── week1/
    ├── week2/
    ├── week3/
    ├── week4/
    ├── week5/
    └── week6/
```

---

## 三、各模块详细说明

### 3.1 `configs/` —— 实验配置文件

系统通过 YAML 文件参数化实验，三个配置文件对应不同的实验阶段：

#### `graph.yaml` —— 图生成参数

```yaml
graph_type: community   # 拓扑类型：community / random_geometric / small_world / scale_free
num_nodes: 200          # 节点数量
seed: 0                 # 随机种子
num_pairs: 20           # 实验中测试的起止点对数
min_delay_ms: 1         # 边延迟最小值
max_delay_ms: 10        # 边延迟最大值
```

#### `brian2loihi.yaml` —— SNN 模拟参数

```yaml
backend: brian2loihi    # 后端选择
dt_ms: 1                # 离散时间步长 = 1ms
threshold: 1.0          # 神经元发放阈值
weight: 1.1             # 突触权重（略高于阈值，保证单次脉冲触发）
refractory_ms: 1000     # 不应期 = 1000ms（防止神经元多次发放）
seed: 0
```

#### `noxim.yaml` —— 外部 NoC 模拟器参数

```yaml
mesh_rows: 8            # 8x8 mesh 拓扑
mesh_cols: 8
noxim_root: ~/code/noxim-master
noxim_bin: ~/code/noxim-master/bin/noxim
noxim_config_path: ~/code/noxim-master/config_examples/default_configMeshNoHUB.yaml
noxim_power_path: ~/code/noxim-master/bin/power.yaml
noxim_packet_size: 2
noxim_warmup_cycles: 0
noxim_simulation_margin_cycles: 200
seed: 0
```

---

### 3.2 `graph/` —— 图生成与经典算法模块

#### `complex_graph_generator.py` —— 生成复杂拓扑图

**核心函数**：`generate_complex_graph(graph_type, num_nodes, seed, ...)`

支持 4 种拓扑类型：

| 类型 | 原理 | 关键参数 |
|---|---|---|
| `random_geometric` | 节点均匀分布在单位方形中，距离小于半径的节点对按概率连边 | `radius`, `edge_prob` |
| `small_world` | 节点在圆上排列，每个节点连接 k 个近邻，按概率重连 | `k`, `rewire_prob` |
| `scale_free` | 从 m0 个种子节点开始，新节点按度优先连接到 m 个已有节点 | `m0`, `m` |
| `community` | 节点分簇，簇内高密度连边，簇间低密度连边 + 保证连通 | `num_communities`, `p_intra`, `p_inter` |

所有拓扑默认添加强连通主干环（backbone cycle），保证 `ensure_strongly_connected=True`。

**节点属性**：每个节点有 `x`、`y` 坐标和 `region` 标签。

**边属性**：`assign_edge_attributes()` 函数为每条边计算：
- `base_cost`：基于欧氏距离 + 随机抖动 ∈ [0.8, 1.2]
- `delay_ms`：将 base_cost 线性映射到 [min_delay_ms, max_delay_ms]
- `state`：边状态，默认为 `"normal"`（`"blocked"` 表示阻塞）

#### `graph_baseline.py` —— Dijkstra 基线算法

| 函数 | 作用 |
|---|---|
| `dijkstra_path(G, start, target)` | 按 `base_cost` 权重求最短路径 |
| `dijkstra_delay_path(G, start, target)` | 按 `delay_ms` 权重求最短路径 |
| `sample_start_target_pairs(G, num_pairs)` | 随机采样起止点对 |
| `evaluate_dijkstra_pairs(G, pairs)` | 批量评估，返回 DataFrame（路径、代价、跳数） |

#### `graph_io.py` —— 图持久化

| 函数 | 作用 |
|---|---|
| `save_graph_json(G, path)` | 将 NetworkX 有向图导出为 JSON |
| `load_graph_json(path)` | 从 JSON 还原 NetworkX 有向图 |
| `save_results_json(data, path)` | 将任意结果字典写入 JSON |

#### `graph_metrics.py` —— 图结构统计

`compute_graph_metrics(G)` 计算：节点数、边数、密度、强连通性、入度/出度均值和标准差、延迟均值和极值、区域直方图。

#### `visualization.py` —— 图可视化

`plot_graph_with_path(G, path, save_path)`：
- 非路径边用浅灰色
- 路径边用红色高亮
- 节点按 `region` 属性着色（tab10 colormap）
- 起点标为绿色方块，终点标为金色星形
- 输出高分辨率 PNG

---

### 3.3 `loihi_planner/` —— 神经形态规划器核心

这是整个项目的核心模块。数据流如下：

```
输入图 G(start, target)
    │
    ▼
loihi_wavefront.py ───────────────┐
  │ 将图节点→LIF神经元组          │
  │ 将边→带延迟的突触             │
  │ 起点注入脉冲                  │
  │ 运行 SNN 模拟                 │
  │ 记录各节点首次发放时间        │
  ▼                               │
spike_trace_by_neuron              │
  │                               │
  ▼                               │
parent_trace.py ◄─────────────────┘
  │ 对每个发放节点，比较所有前驱
  │ 的"前驱发放时间 + 边延迟"
  │ 选择最早到达的前驱作为父节点
  ▼
parent_dict: {node: parent}
  │
  ▼
path_reconstruction.py
  │ 从 target 沿 parent 反向追踪到 start
  │ 检测环路，防止死循环
  ▼
snn_path: [start, ..., target]
  │
  ▼
path_compare.py
  │ compute_path_cost() + compare_snn_path_with_dijkstra()
  │ 比较 SNN 路径与 Dijkstra 最优路径：
  │  - optimality_ratio
  │  - same_path / same_cost
  ▼
stdp_trace.py
  │ 对每条边标记是否在 parent 链上
  │ parent 边: stdp_weight = 1.0（增强）
  │ 非 parent 边: stdp_weight = 0.0
```

#### `_brian2_runner.py` —— 后端加载

**核心数据结构**：`Brian2LoihiBackend` dataclass，包含 `brian2` 模块引用、`brian2loihi` 模块引用、`name`、`mode`、`device_name`。

**两种运行模式**：

1. **object_api 模式**：直接创建 `LoihiNeuronGroup`、`LoihiSynapses` 等对象（较新版本）
2. **brian2_device 模式**：通过 `brian2.set_device()` 使用 Brian2 设备接口（旧版本兼容）

两种模式在 `loihi_wavefront.py` 中都有对应的实现路径。

#### `loihi_wavefront.py` —— 核心：SNN 波前路由

**核心函数**：`run_loihi_wavefront(G, start, target, delay_attr, sim_time_ms, ...)`

**工作流程**：
1. 将图节点映射到连续整数索引
2. 创建 Loihi 神经元组：`decay_v=0`（无泄漏，纯积分）、`decay_I=4096`（电流慢衰减）
3. 创建发放阈值 = `round(threshold * 64)`（Loihi 整数表示）
4. 在起点创建脉冲生成器，注入初始脉冲
5. 将图的每条边转为带延迟的突触：`synapse.delay = edge_delay - 1`（补偿 1ms 的轴突延迟）
6. 按延迟值分组，同延迟的边合并到一个 `LoihiSynapses` 对象
7. 运行模拟，记录每个节点的首次发放时间

**返回**：各节点首次发放时间、目标到达时间、活跃神经元数、成功与否。

#### `wavefront_reference.py` —— CPU 参考算法（真值）

**核心函数**：`event_driven_wavefront(G, start, target, delay_attr)`

用 `heapq` 实现的 Dijkstra-like 事件驱动波前传播。用于验证 SNN 结果是否准确。返回每个节点的最早到达时间、访问顺序。

#### `parent_trace.py` —— 推断父节点

**核心函数**：`infer_parent_trace_from_spikes(G, spike_times_by_neuron, start, delay_attr, tolerance_ms)`

对每个发放的节点，遍历其所有前驱：
```
prediction = spike_time[pred] + edge_delay
if |prediction - post_spike_time| <= tolerance_ms:
    候选父节点，选 earliest + tiebreaker
```
返回 `{node_id: parent_id}` 字典。

#### `path_reconstruction.py` —— 反向追踪路径

**核心函数**：`reconstruct_path_from_parent(parent_trace, start, target)`

从 target 节点开始，沿 parent 指针反向走回到 start，检测环路。返回正向路径列表 `[start, ..., target]`。

#### `path_compare.py` —— 路径对比

**核心函数**：`compare_snn_path_with_dijkstra(G, snn_path, dijkstra_path)`

输出：
- `snn_cost` / `dijkstra_cost`：两个路径的总代价
- `optimality_ratio`：SNN 代价 / Dijkstra 代价（≤ 1.0 表示最优）
- `same_path` / `same_cost`：路径/代价是否相同

#### 三个验证 Demo

| 脚本 | 验证内容 | 规模 |
|---|---|---|
| `loihi_lif_demo.py` | 单神经元接收脉冲→发放 | 1 个神经元 |
| `loihi_delay_demo.py` | 突触延迟是否准确传递 | 2 个神经元 |
| `loihi_small_wavefront_demo.py` | 小图波前传播 | 5 个神经元，4 条边 |

#### 辅助模块

| 脚本 | 作用 |
|---|---|
| `backend_check.py` | 检测 Brian2 / Brian2Loihi 是否可用，返回版本信息 |
| `loihi_config.py` | 从 YAML 加载 SNN 配置，规范化参数 |
| `spike_trace.py` | 脉冲数据的 CSV 序列化/反序列化 |
| `stdp_trace.py` | 构建 STDP 分析表，标记哪些边在 parent 链上 |

---

### 3.4 `noc/` —— NoC 外部模拟器接口

这一层已经接入官方 Noxim 源码树，负责把 Loihi 脉冲轨迹转换为
Noxim 的 `hardcoded` 交通文件，并解析 Noxim 的 JSON 统计输出。

| 脚本 | 作用 |
|---|---|
| `noxim_wrapper.py` | 子进程调用 Noxim 二进制，捕获 stdout/stderr，返回结构化结果 |
| `traffic_table.py` | 生成 Noxim 格式的样例流量表，以及 `hardcoded` 交通文件 |
| `parse_noxim_output.py` | 从 Noxim 文本输出或 JSON 统计中提取 `global_average_delay_cycles`、`network_throughput_flits_per_cycle` 等指标 |

`run_noxim()` 的降级逻辑：如果 Noxim 二进制、配置文件或 power 文件不存在，返回 `{"status": "skipped"}` 而不是崩溃。

---

### 3.5 `experiments/` —— 实验入口

按周组织的 4 个实验脚本，每个都通过 `--config` 和 `--output` 命令行参数驱动：

| 周 | 脚本 | 实验内容 | 核心输出 |
|---|---|---|---|
| Week1 | `run_week1_toolchain_check.py` | 工具链完整性检查（无 CLI 参数） | `backend_check.json`, `loihi_demo_summary.json` |
| Week2 | `run_graph_baseline.py` | 生成图 + Dijkstra 基线 | `graph.json`, `graph_metrics.json`, `dijkstra_results.csv`, `example_path.png` |
| Week3 | `run_loihi_wavefront.py` | Loihi SNN 波前传播，对比参考算法 | `wavefront_results.csv`, `spike_trace_pair_0.csv` |
| Week4 | `run_stdp_path_reconstruction.py` | 完整 STDP 路径重建 + 最优性对比 | `stdp_path_results.csv`, `pair_0_stdp_trace.csv`, `pair_0_path_compare.json` |
| Week5 | `run_dynamic_start_and_relay.py` | Grid/Place 动态起点 + relay 阻塞/惩罚重规划 | `dynamic_start_results.csv`, `blocked_edge_results.json`, `penalized_edge_results.json` |
| Week6 | `run_noc_validation.py` | 映射策略 + Noxim 硬编码流量验证 | `noc_results.csv`, `fig_average_hop_by_mapping.png`, `fig_energy_proxy_by_mapping.png` |

**实验流水线**：
```
Week1 (验证环境) → Week2 (传统基线) → Week3 (SNN 波前) → Week4 (路径重建与评估)
```

### 3.6 `tests/` —— 测试套件

每个核心模块都有对应的测试文件，验证正确性和边界条件。共 20 个测试文件，覆盖所有关键模块。

运行方式：
```bash
bash scripts/run_tests.sh
# 或直接
pytest
```

---

## 四、核心数据流与运行逻辑

### 4.1 SNN 波前路由原理

假设图有 4 个节点，结构如下：

```
  0 ──(delay=3)──▶ 2
  │                │
  (delay=1)        (delay=1)
  │                │
  ▼                ▼
  1 ──(delay=1)──▶ 3
```

起点 = 0，目标 = 3。

1. **t=0**：起点神经元 0 收到输入脉冲，发放
2. **t=1**：脉冲经 delay=1 的突触到达神经元 1，神经元 1 发放
3. **t=2**：脉冲从 1 经 delay=1 到达神经元 3，神经元 3 发放（路径 0→1→3，总延迟=2）
4. **t=3**：脉冲从 0 经 delay=3 到达神经元 2，神经元 2 发放
5. **t=4**：脉冲从 2 经 delay=1 到达神经元 3（已发放，忽略）

结果：目标节点首次发放时间为 t=2，对应最短路径 0→1→3。

### 4.2 关键设计决策

**不应期 = 1000ms**：远大于任意路径延迟，保证每个神经元只发放一次。这是因为波前路由中，只有最早到达的脉冲是有意义的（对应最短路径）。

**decay_v = 0**：神经元膜电位不泄漏，纯积分模式。保证任意大小的输入电流都能可靠触发。

**weight = 1.1 > threshold = 1.0**：单次突触前脉冲就能驱动突触后神经元发放，保证波前正确传播。

**synapse.delay = edge_delay - 1**：Brian2Loihi 的突触延迟定义是从 pre-spike 时间开始计算，需要补偿 1ms 的轴突延迟。

---

## 五、运行方式

### 5.1 环境准备

```bash
# 创建 conda 环境
conda create -n neuromorphic_noc python=3.10 -y
conda activate neuromorphic_noc

# 安装依赖
cd /Users/ares/code/neuromorphic_noc_navigation
pip install -r requirements.txt
```

### 5.2 运行实验

```bash
# Week1 - 工具链检查（无需参数）
python experiments/run_week1_toolchain_check.py

# Week2 - Dijkstra 基线
python experiments/run_graph_baseline.py \
    --config configs/graph.yaml \
    --output results/week2

# Week3 - Loihi SNN 波前
python experiments/run_loihi_wavefront.py \
    --graph results/week2/graph.json \
    --config configs/brian2loihi.yaml \
    --output results/week3

# Week4 - STDP 路径重建
python experiments/run_stdp_path_reconstruction.py \
    --graph results/week2/graph.json \
    --config configs/brian2loihi.yaml \
    --output results/week4

# Week5 - 动态起点与 relay 重规划
python experiments/run_dynamic_start_and_relay.py \
    --graph results/week2/graph.json \
    --config configs/brian2loihi.yaml \
    --output results/week5

# Week6 - Noxim 验证
python experiments/run_noc_validation.py \
    --graph results/week2/graph.json \
    --loihi-config configs/brian2loihi.yaml \
    --noc-config configs/noxim.yaml \
    --output results/week6
```

---

## 六、关键类与函数速查

### 图模块 (`graph`)

| 函数 | 所在文件 | 作用 |
|---|---|---|
| `generate_complex_graph()` | `complex_graph_generator.py` | 生成 4 种拓扑的有向图 |
| `dijkstra_path()` | `graph_baseline.py` | Dijkstra 最短路径 |
| `save_graph_json()` / `load_graph_json()` | `graph_io.py` | 图持久化 |
| `compute_graph_metrics()` | `graph_metrics.py` | 图结构统计 |
| `plot_graph_with_path()` | `visualization.py` | 图可视化 |

### 规划器模块 (`loihi_planner`)

| 函数 | 所在文件 | 作用 |
|---|---|---|
| `run_loihi_wavefront()` | `loihi_wavefront.py` | **核心**：SNN 波前路由 |
| `event_driven_wavefront()` | `wavefront_reference.py` | CPU 参考波前（真值） |
| `infer_parent_trace_from_spikes()` | `parent_trace.py` | 推断父节点关系 |
| `reconstruct_path_from_parent()` | `path_reconstruction.py` | 反向追踪路径 |
| `compare_snn_path_with_dijkstra()` | `path_compare.py` | 路径最优性对比 |
| `load_brian2loihi_backend()` | `_brian2_runner.py` | 后端加载 |

### NoC 模块 (`noc`)

| 函数 | 所在文件 | 作用 |
|---|---|---|
| `run_noxim()` | `noxim_wrapper.py` | 封装 Noxim 子进程调用 |
| `run_noxim_with_hardcoded_traffic()` | `noxim_wrapper.py` | 运行 Noxim 硬编码交通验证 |
| `parse_noxim_output()` / `parse_noxim_stats_file()` | `parse_noxim_output.py` | 解析 Noxim 文本输出或 JSON 统计 |
| `save_noxim_hardcoded_traffic()` | `traffic_table.py` | 生成 Noxim `hardcoded` 交通文件 |
| `save_sample_noxim_traffic_table()` | `traffic_table.py` | 生成样例流量表 |
