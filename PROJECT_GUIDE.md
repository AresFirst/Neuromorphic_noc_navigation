# 神经形态 NoC 导航项目解析

## 一、项目总览

本项目探索**用脉冲神经网络（SNN）在 NoC（Network-on-Chip，片上网络）上做路由规划**。核心思路是把图上的节点映射为 Loihi 风格的 LIF 神经元，图的边映射为带延迟的突触，用脉冲波前（wavefront）传播来找到最短路径。

**关键实验假设**：脉冲到达时间 = 路径代价。波前从起点出发，经过不同延迟的突触传播到各节点。目标节点最先接收到脉冲的时刻，代表了起点到目标的最短路径延迟。通过合理的 STDP 规则和 parent-trace 反向追踪，就能重建出实际路径。

**完整流程**：

```
连续坐标 (x,y)              图拓扑 G
     │                         │
     ▼                         ▼
  localization/           graph/
  动态起点定位             Dijkstra 基线
     │                         │
     ▼                         ▼
  loihi_planner/ ──────────────┘
  SNN 波前路由 → parent追踪 → 路径重建 → 最优性对比
     │
     ▼
  noc/
  神经元→NoC core 映射 → 脉冲→数据包 → Noxim 仿真 → 性能指标
```

**项目仓库地址**：`/Users/ares/code/neuromorphic_noc_navigation`

---

## 二、目录结构总览

```
neuromorphic_noc_navigation/
├── README.md                          # 项目说明（六周实验计划）
├── requirements.txt                   # Python 依赖
├── conftest.py                        # pytest 全局配置
│
├── configs/                           # ☆ 实验参数配置（YAML）
│   ├── graph.yaml                     #   图生成参数
│   ├── brian2loihi.yaml               #   SNN 模拟参数
│   └── noxim.yaml                     #   NoC/Noxim 模拟器参数
│
├── graph/                             # ☆ 图生成、传统算法、可视化
│   ├── __init__.py
│   ├── complex_graph_generator.py     #   生成 4 种复杂拓扑图
│   ├── graph_baseline.py              #   Dijkstra 最短路径（传统基线）
│   ├── graph_io.py                    #   图的 JSON 序列化/反序列化
│   ├── graph_metrics.py               #   图结构统计
│   └── visualization.py              #   Matplotlib 图可视化
│
├── localization/                      # ☆ 动态起点定位模块
│   ├── __init__.py
│   ├── grid_cells.py                  #   Grid cell 连续坐标编码
│   ├── place_cells.py                 #   Place cell 位置匹配
│   └── dynamic_start.py               #   连续位置→图节点估计
│
├── loihi_planner/                     # ☆ 神经形态规划器核心
│   ├── __init__.py
│   ├── _brian2_runner.py             #   Brian2/Brian2Loihi 后端加载
│   ├── backend_check.py              #   后端可用性检测
│   ├── loihi_config.py               #   运行时配置
│   ├── loihi_lif_demo.py             #   单神经元 LIF 验证
│   ├── loihi_delay_demo.py           #   突触延迟验证
│   ├── loihi_small_wavefront_demo.py #   小图波前传播验证
│   ├── loihi_wavefront.py            #   ☆ 核心：SNN 波前路由
│   ├── wavefront_reference.py        #   CPU 参考波前算法（真值）
│   ├── spike_trace.py                #   脉冲 CSV 读写
│   ├── parent_trace.py               #   脉冲时间→父节点推断
│   ├── path_reconstruction.py        #   父关系→完整路径反向追踪
│   ├── path_compare.py               #   SNN vs Dijkstra 路径对比
│   ├── stdp_trace.py                 #   STDP 权重变化表
│   ├── dynamic_replanning.py         #   从连续坐标重新规划
│   └── relay_controller.py           #   动态边阻塞/惩罚
│
├── noc/                               # ☆ NoC 外部模拟器接口
│   ├── __init__.py
│   ├── mapping.py                     #   神经元→NoC core 映射
│   ├── packet_trace.py               #   Spike trace → packet trace
│   ├── traffic_table.py              #   Packet trace → Noxim 流量文件
│   ├── noc_proxy_metrics.py          #   NoC hop/energy 代理指标
│   ├── noc_experiment.py             #   单次 NoC 验证流程编排
│   ├── noxim_wrapper.py              #   Noxim 子进程调用
│   └── parse_noxim_output.py         #   解析 Noxim 输出指标
│
├── experiments/                       # ☆ 实验入口脚本
│   ├── run_week1_toolchain_check.py   #   Week1: 工具链检查
│   ├── run_graph_baseline.py          #   Week2: Dijkstra 基线
│   ├── run_loihi_wavefront.py         #   Week3: Loihi 波前验证
│   ├── run_stdp_path_reconstruction.py # Week4: STDP 路径重建
│   ├── run_dynamic_start_and_relay.py  # Week5: 动态起点与重规划
│   └── run_noc_validation.py          # Week6: NoC 验证
│
├── tests/                             # 单元测试
│   └── ... (12 个测试文件)
│
├── scripts/
│   └── run_tests.sh
│
└── results/                           # 实验结果输出
    ├── week1/ ... week6/
```

---

## 三、重点专题：地图 → NoC 架构的映射全流程

这是整个项目最核心的架构问题。下面从**地图生成** → **神经元放置** → **SNN 波前路由** → **脉冲转数据包** → **Noxim 仿真**的完整链路进行详细说明。

### 3.1 第一步：地图生成 (`graph/complex_graph_generator.py`)

**在哪里修改地图**：配置 `configs/graph.yaml` 中的参数，或直接调用 `generate_complex_graph()`。

地图是一个 NetworkX `DiGraph`（有向图），每个节点代表一个逻辑路由器/处理单元，每条边代表一个可用通信链路。

**节点属性**（每个节点必须有的数据）：
| 属性 | 类型 | 含义 |
|---|---|---|
| `x` | float (0~1) | 归一化 X 坐标，用于空间定位和 core 映射 |
| `y` | float (0~1) | 归一化 Y 坐标 |
| `region` | int (0~3) | 所属区域/社区，用于 community 映射策略 |

**边属性**（每条边必须有的数据）：
| 属性 | 类型 | 含义 |
|---|---|---|
| `delay_ms` | int | 链路延迟（毫秒），也是 SNN 突触延迟 |
| `base_cost` | float | 链路基础代价（Dijkstra 用） |
| `state` | str | `"normal"`、`"blocked"` 或 `"penalized"` |
| `original_delay_ms` | int | 原始延迟，用于恢复中被惩罚/阻塞的边 |

**修改地图的入口**：
- **修改拓扑结构**：在 `configs/graph.yaml` 中改 `graph_type`、`num_nodes` 等参数
- **修改节点坐标分布**：修改 `complex_graph_generator.py` 中各拓扑类型的坐标生成逻辑
- **修改边延迟计算**：修改 `assign_edge_attributes()` 函数中的距离→延迟映射公式

### 3.2 第二步：动态起点定位 (`localization/`)

**为什么需要**：真实场景中，Agent 的当前位置是连续坐标 `(x, y)`，需要先"捕捉"到图中最近或最合适的节点上。

#### `place_cells.py` —— 位置细胞层

模拟海马体的位置细胞：每个图节点是一个"位置野"，当 Agent 靠近该节点时激活最强。

```python
layer = PlaceCellLayer(node_positions={0: (0.2, 0.3), 1: (0.5, 0.7), ...}, sigma=0.1)
activations = layer.activations(x, y)    # 软激活：{node_id: similarity}
best_node = layer.winner_take_all(x, y)  # 硬分配：返回最近节点
```

**核心参数 `sigma`**：控制位置野的宽度。`sigma=0.1` 表示 Agent 离节点 ~0.1 距离时仍有 ~60% 激活。值越小，定位越精确但要求 Agent 必须在节点附近。

#### `grid_cells.py` —— 网格细胞编码

模拟内嗅皮层的网格细胞：将 2D 位置编码为高维周期向量（默认 72 维）。

```python
encoder = GridCellEncoder(wavelengths=[0.2, 0.4, 0.8, 1.6], phases=[0, pi/3, 2*pi/3])
vector = encoder.encode(x, y)  # 72 维向量
```

多尺度波长提供"粗定位+精定位"：短波长捕捉局部细节，长波长消除周期性歧义。

#### `dynamic_start.py` —— 定位入口

```python
start_node = estimate_start_node_from_position(G, x, y, sigma=0.1)
```

内部调用 `PlaceCellLayer.winner_take_all()`，返回最近的图节点 ID。

### 3.3 第三步：SNN 波前路由 (`loihi_planner/loihi_wavefront.py`)

**在哪里修改神经元集群**：`loihi_wavefront.py` 的 `run_loihi_wavefront()` 函数。

这是将图转换为 SNN 的核心。转换规则：

```
图 G(V, E)                    SNN
─────────────────────────────────────
每个节点 v ∈ V          →   一个 LIF 神经元
每条边 (u→v) ∈ E       →   一个带延迟的兴奋性突触
边的 delay_ms 属性      →   突触传导延迟
起点 start              →   输入脉冲注入该神经元
目标 target             →   监测该神经元的首次发放时间
```

**神经元参数（在哪里修改）**：通过 `configs/brian2loihi.yaml` 或直接传入 `run_loihi_wavefront()`：

| 参数 | 默认值 | 含义 | 修改位置 |
|---|---|---|---|
| `threshold` | 1.0 | 发放阈值，越低越敏感 | `brian2loihi.yaml` |
| `weight` | 1.1 | 突触权重，>threshold 保证传播 | `brian2loihi.yaml` |
| `refractory_ms` | 1000 | 不应期 >> 最大路径延迟（每个神经元只发放一次） | `brian2loihi.yaml` |
| `decay_v` | 0 (硬编码) | 膜电位不泄漏，纯积分 | `loihi_wavefront.py` |
| `decay_I` | 4096 (硬编码) | 电流衰减极慢 | `loihi_wavefront.py` |

**关键设计决策**：
- `weight=1.1 > threshold=1.0`：确保单次突触前脉冲就能驱动突触后神经元发放
- `refractory=1000ms`：远大于最大路径总延迟，保证每个节点只发放一次（仅记录最早到达）
- `decay_v=0`：无泄漏，保证无论脉冲何时到达都能积累到发放阈值

**两种运行模式**（由 `_brian2_runner.py` 自动检测）：
1. **object_api 模式**：直接创建 `LoihiNeuronGroup`、`LoihiSynapses`（新版本）
2. **brian2_device 模式**：通过 `brian2.set_device()` 使用标准 Brian2 接口

### 3.4 第四步：父节点追踪 → 路径重建 (`loihi_planner/`)

```python
# 1. 从脉冲时间推断每个节点的"父节点"——最早触发它的前驱
parent_trace = infer_parent_trace_from_spikes(G, spike_times_by_neuron, start, delay_attr)

# 2. 从目标沿父节点反向追踪到起点
path = reconstruct_path_from_parent(parent_trace, start, target)

# 3. 与 Dijkstra 最优路径对比
comparison = compare_snn_path_with_dijkstra(G, snn_path, dijkstra_path)
```

**父节点推断算法**：
对每个发放节点，遍历所有前驱：
```
prediction = 前驱发放时间 + 边延迟
if |prediction - 本节点发放时间| ≤ tolerance_ms:
    候选父节点中选 prediction 最小的
```

### 3.5 第五步：神经元 → NoC Core 映射 (`noc/mapping.py`)

**这是回答"地图如何映射到 NoC 架构"的关键环节。**

NoC 是一个 2D Mesh 网络，有 `mesh_rows × mesh_cols` 个物理 core。每个 graph 节点（SNN 神经元）必须分配到某个物理 core 上执行。

```python
core_mapping = create_core_mapping(G, mesh_rows=8, mesh_cols=8, strategy="topology")
# 返回：{node_id: core_id, ...}
```

**三种映射策略**：

| 策略 | 原理 | 适用场景 |
|---|---|---|
| `"random"` | 每个节点均匀随机分配到一个 core | 基线对照，不利用空间信息 |
| `"topology"` | 利用节点的 `(x, y)` 坐标，映射到最近的物理 core。公式：`row = round(y * (mesh_rows-1))`, `col = round(x * (mesh_cols-1))` | 空间连续的图拓扑 |
| `"community"` | 按 `region` 属性分组，同一社区的节点尽量放在相邻的 core 上（用曼哈顿距离扩张分配） | 社区结构的图拓扑 |

**在哪里修改映射策略**：`configs/noxim.yaml` 中的 `mapping_strategies` 字段，或直接传入 `create_core_mapping()` 的 `strategy` 参数。

**修改映射逻辑的位置**：`noc/mapping.py` 中的 `create_core_mapping()` 函数。

### 3.6 第六步：脉冲 → 数据包 (`noc/packet_trace.py`)

**这是回答"SNN 脉冲如何发送到 Noxim"的关键环节。**

SNN 模拟产生的数据是 **脉冲发放时间表**（spike trace）：`{神经元ID: 首次发放时间}`。这需要转换为 NoC 可理解的 **数据包跟踪**（packet trace）：`{cycle, src_core, dst_core, packet_size}`。

```python
packet_trace = spike_trace_to_packet_trace(G, spike_times_by_neuron, core_mapping)
```

**转换规则**：
1. 遍历图的每条边 `(src_neuron, dst_neuron)`
2. 跳过 `state == "blocked"` 的边
3. 检查两端神经元是否都发放了脉冲
4. 验证时间关系：`spike_time[src] + delay ≈ spike_time[dst]`（在 tolerance_ms 内）
5. 如果关系成立，说明波前确实沿这条边传播了
6. 通过 `core_mapping` 将 `(src_neuron, dst_neuron)` 转换为 `(src_core, dst_core)`
7. 生成一条 packet 记录，packet_type 标记为 `"spike"`

**输出 DataFrame 结构**：

| 列名 | 类型 | 含义 |
|---|---|---|
| `cycle` | int | 注入时间（对应脉冲发放时间） |
| `src_neuron` | int | 源神经元 ID |
| `dst_neuron` | int | 目标神经元 ID |
| `src_core` | int | 源物理 core ID |
| `dst_core` | int | 目标物理 core ID |
| `packet_type` | str | `"spike"` 或 `"relay"` |
| `packet_size` | int | 数据包大小（flits） |

### 3.7 第七步：Packet Trace → Noxim 流量文件 (`noc/traffic_table.py`)

Noxim 需要特定格式的流量文件。有两种格式：

**hardcoded 格式**（逐周期指定）：
```
# 每个周期一行 "src_core dst_core"，以 "-1 -1" 结束一个周期
0 1
-1 -1
3 7
2 4
-1 -1
```

**traffic_table 格式**（统计聚合）：
```
# src_x src_y dst_x dst_y packet_size injection_time
0 0 1 1 2 0
1 1 2 2 2 4
```

```python
# 转换为 hardcoded 格式
lines = packet_trace_to_hardcoded_traffic_lines(packet_trace)
# 转换为 traffic table 格式
table = packet_trace_to_traffic_table(packet_trace, num_cores)
```

### 3.8 第八步：Noxim 仿真 (`noc/noxim_wrapper.py`)

Noxim 是一个 C++ 实现的开源 NoC 周期精确模拟器。本项目通过命令行子进程调用。

```python
result = run_noxim_with_hardcoded_traffic(
    noxim_bin="~/code/noxim-master/bin/noxim",
    config_path="~/code/noxim-master/config_examples/default_configMeshNoHUB.yaml",
    traffic_file="traffic_hardcoded.txt",
    output_dir="results/noc_output/",
    power_path="~/code/noxim-master/bin/power.yaml",
    mesh_rows=8, mesh_cols=8, sim_cycles=500, seed=42
)
```

**Noxim 输出指标**（由 `parse_noxim_output.py` 解析）：
- `global_average_delay_cycles`：平均包延迟（周期数）
- `network_throughput_flits_per_cycle`：网络吞吐量
- `total_energy_j`：总能耗（焦耳）
- `max_delay_cycles`：最大包延迟

### 3.9 代理指标（无需 Noxim）(`noc/noc_proxy_metrics.py`)

在没有 Noxim 的情况下，也可以通过曼哈顿距离快速估算 NoC 性能：

```python
metrics = compute_noc_proxy_metrics(packet_trace, mesh_rows, mesh_cols)
# 返回：num_packets, average_hop, max_hop, total_hop, energy_proxy, hotspot_core
```

`energy_proxy = Σ(packet_size × manhattan_hop)` 是对能耗的粗略估算。

### 3.10 完整编排 (`noc/noc_experiment.py`)

`run_single_noc_validation()` 函数将以上所有步骤串联成一个完整流水线：

```
create_core_mapping()
    → run_loihi_wavefront()          # SNN 波前路由
    → infer_parent_trace_from_spikes() # 父节点追踪
    → reconstruct_path_from_parent()   # 路径重建
    → build_stdp_trace_table()         # STDP 分析
    → spike_trace_to_packet_trace()    # 脉冲→数据包
    → compute_noc_proxy_metrics()      # 代理指标
    → packet_trace_to_traffic_table()  # 流量文件
    → run_noxim_with_hardcoded_traffic() # Noxim 仿真
    → 汇总所有结果
```

---

## 四、重点专题：修改指南

### 4.1 如果要修改地图

| 要修改的内容 | 修改位置 | 具体操作 |
|---|---|---|
| 拓扑类型/节点数 | `configs/graph.yaml` | 改 `graph_type`、`num_nodes` |
| 拓扑生成算法参数 | `graph/complex_graph_generator.py` | 改 `generate_complex_graph()` 中的 kwargs 默认值 |
| 边延迟计算方式 | `graph/complex_graph_generator.py` | 修改 `assign_edge_attributes()` 的距离→延迟映射公式 |
| 节点坐标分布 | `graph/complex_graph_generator.py` | 修改各拓扑生成函数中的 `x`、`y` 赋值逻辑 |
| 节点区域标签 | `graph/complex_graph_generator.py` | 修改 `_quadrant_region()` 或各拓扑的分区逻辑 |
| 图持久化格式 | `graph/graph_io.py` | 修改 `save_graph_json()` / `load_graph_json()` |
| 阻塞某些边 | `loihi_planner/relay_controller.py` | 用 `RelayController.block_edge(u, v)` 运行前动态阻塞 |

### 4.2 如果要修改神经元集群参数

| 要修改的内容 | 修改位置 | 具体操作 |
|---|---|---|
| 发放阈值 | `configs/brian2loihi.yaml` | 改 `threshold` 值 |
| 突触权重 | `configs/brian2loihi.yaml` | 改 `weight` 值 |
| 不应期 | `configs/brian2loihi.yaml` | 改 `refractory_ms` 值 |
| 积分/衰减参数 | `loihi_planner/loihi_wavefront.py` | 修改 `run_loihi_wavefront()` 中的 `decay_v`、`decay_I` |
| 神经元分组逻辑 | `loihi_planner/loihi_wavefront.py` | 修改 `run_loihi_wavefront()` 中 NeuronGroup 的创建逻辑 |
| 突触分组逻辑（按延迟分组） | `loihi_planner/loihi_wavefront.py` | 修改按 `delay` 值分组 edges 的逻辑 |
| 添加新的神经元模型 | `loihi_planner/loihi_wavefront.py` | 在 brian2_device 模式分支中添加新方程或新参数 |

### 4.3 如果要修改 NoC 映射和仿真

| 要修改的内容 | 修改位置 | 具体操作 |
|---|---|---|
| Mesh 尺寸 | `configs/noxim.yaml` | 改 `mesh_rows`、`mesh_cols` |
| 映射策略 | `configs/noxim.yaml` 或调用时 | 改 `mapping_strategies` 或在代码中传入 `strategy` 参数 |
| 映射算法 | `noc/mapping.py` | 修改 `create_core_mapping()` 或新增 strategy 分支 |
| 脉冲→数据包转换规则 | `noc/packet_trace.py` | 修改 `spike_trace_to_packet_trace()` 的时间验证逻辑 |
| 数据包大小 | `configs/noxim.yaml` | 改 `noxim_packet_size` |
| Noxim 二进制/配置路径 | `configs/noxim.yaml` | 改 `noxim_bin`、`noxim_config_path`、`noxim_power_path` |
| 代理指标计算 | `noc/noc_proxy_metrics.py` | 修改 `compute_noc_proxy_metrics()` |
| 流量文件格式 | `noc/traffic_table.py` | 修改 `packet_trace_to_hardcoded_traffic_lines()` |

### 4.4 如果要修改动态重规划逻辑

| 要修改的内容 | 修改位置 | 具体操作 |
|---|---|---|
| 定位 sigma（位置野宽度） | `localization/place_cells.py` 或调用时 | 修改 `PlaceCellLayer(sigma=...)` 和 `estimate_start_node_from_position(sigma=...)` |
| Grid cell 编码参数 | `localization/grid_cells.py` | 修改 `GridCellEncoder` 的 `wavelengths` 和 `phases` 默认值 |
| 重规划流程 | `loihi_planner/dynamic_replanning.py` | 修改 `replan_from_position()` 中的调用顺序或添加新步骤 |
| 边阻塞/惩罚因子 | `loihi_planner/relay_controller.py` | 修改 `penalize_edge(factor=...)` 的惩罚倍数 |

---

## 五、各模块详细说明

### 5.1 `configs/` —— 实验配置

#### `graph.yaml`

```yaml
graph_type: community   # random_geometric / small_world / scale_free / community
num_nodes: 200
seed: 0
num_pairs: 20
min_delay_ms: 1
max_delay_ms: 10
```

#### `brian2loihi.yaml`

```yaml
backend: brian2loihi
dt_ms: 1
threshold: 1.0
weight: 1.1
refractory_ms: 1000
seed: 0
```

#### `noxim.yaml`

```yaml
mesh_rows: 8
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

### 5.2 `graph/` —— 图生成与经典算法

#### `complex_graph_generator.py`

**核心函数**：`generate_complex_graph(graph_type, num_nodes, seed, ...)`

| 拓扑类型 | 原理 | 关键参数 |
|---|---|---|
| `random_geometric` | 节点均匀分布在单位方形中，距离 < radius 的节点对按概率连边 | `radius`, `edge_prob` |
| `small_world` | 节点在圆上排列，近邻连接 + 概率重连 | `k`, `rewire_prob` |
| `scale_free` | BA 无标度网络：新节点按度优先连接 | `m0`, `m` |
| `community` | 节点分簇，簇内高密度、簇间低密度 + 强连通主干 | `num_communities`, `p_intra`, `p_inter` |

`assign_edge_attributes()` 为每条边计算 `base_cost`（基于欧氏距离+抖动）和 `delay_ms`（cost 线性映射到延迟范围）。

#### `graph_baseline.py`

| 函数 | 作用 |
|---|---|
| `dijkstra_path(G, start, target)` | 按 `base_cost` 求最短路径 |
| `dijkstra_delay_path(G, start, target)` | 按 `delay_ms` 求最短路径 |
| `sample_start_target_pairs(G, num_pairs)` | 随机采样起止点对 |
| `evaluate_dijkstra_pairs(G, pairs)` | 批量评估，返回 DataFrame |

#### `graph_io.py` / `graph_metrics.py` / `visualization.py`

图的 JSON 持久化、结构统计（度、密度、延迟分布）、Matplotlib 可视化（路径红色高亮，region 着色）。

---

### 5.3 `localization/` —— 动态定位

这是一个生物启发式的定位模块，模仿哺乳动物的空间导航系统。

#### `place_cells.py` —— 位置细胞

```python
layer = PlaceCellLayer(node_positions, sigma=0.1)
activations = layer.activations(x, y)     # 软激活：所有节点都有激活值
best = layer.winner_take_all(x, y)        # 硬分配：返回激活最大的节点 ID
```

每个节点是一个高斯位置野中心。`sigma` 控制野宽度。

#### `grid_cells.py` —— 网格细胞

```python
encoder = GridCellEncoder(wavelengths=[0.2, 0.4, 0.8, 1.6], phases=[0, pi/3, 2*pi/3])
vec = encoder.encode(x, y)  # 72 维周期向量
```

为每个 (x, y) 生成一个高维、多尺度的周期性表示，可作为神经网络策略的输入。

#### `dynamic_start.py` —— 定位入口

```python
start_node = estimate_start_node_from_position(G, x, y, sigma=0.1)
```

组合 `PlaceCellLayer` → `winner_take_all`，将连续坐标"捕捉"到最近的图节点。

---

### 5.4 `loihi_planner/` —— 神经形态规划器

#### 后端基础设施

| 文件 | 核心功能 |
|---|---|
| `_brian2_runner.py` | `load_brian2loihi_backend()` 自动发现两种运行模式（object_api / brian2_device） |
| `backend_check.py` | `check_brian2loihi_available()` 检测环境可用性并返回版本 |
| `loihi_config.py` | `load_brian2loihi_config()` 从 YAML 加载/规范化 SNN 参数 |

#### 三个验证 Demo

| 文件 | 验证内容 | 规模 |
|---|---|---|
| `loihi_lif_demo.py` | 单神经元接收脉冲→发放 | 1 个神经元 |
| `loihi_delay_demo.py` | 突触延迟准确传递 | 2 个神经元 |
| `loihi_small_wavefront_demo.py` | 小图波前传播 | 5 个神经元 |

#### 核心路由

| 文件 | 核心功能 |
|---|---|
| `loihi_wavefront.py` | **核心**：`run_loihi_wavefront()` 将图转为 SNN 并运行波前传播 |
| `wavefront_reference.py` | `event_driven_wavefront()` CPU 参考算法（heapq Dijkstra-like） |

#### 路径重建与分析

```
loihi_wavefront (SNN 波前)
    ↓ spike_times_by_neuron
parent_trace (父节点推断)
    ↓ parent_dict
path_reconstruction (反向追踪)
    ↓ path
path_compare (与 Dijkstra 对比)
    ↓ optimality_ratio
stdp_trace (STDP 权重表)
```

| 文件 | 核心函数 | 作用 |
|---|---|---|
| `spike_trace.py` | `save_spike_trace()` / `load_spike_trace()` | 脉冲 CSV 读写 |
| `parent_trace.py` | `infer_parent_trace_from_spikes()` | 从脉冲时间推断父节点 |
| `path_reconstruction.py` | `reconstruct_path_from_parent()` | 沿父节点反向追踪回起点 |
| `path_compare.py` | `compare_snn_path_with_dijkstra()` | 最优性比率、路径一致性 |
| `stdp_trace.py` | `build_stdp_trace_table()` | 标记哪些边在 parent 链上 |

#### 动态重规划（新）

| 文件 | 核心功能 |
|---|---|
| `dynamic_replanning.py` | `replan_from_position(G, x, y, target, ...)` 一站式重规划：定位→波前→父追踪→路径重建 |
| `relay_controller.py` | `RelayController.block_edge()` / `penalize_edge()` / `restore_edge()` 在不破坏原图的前提下动态修改边状态 |

---

### 5.5 `noc/` —— NoC 接口

#### 映射层

| 文件 | 核心功能 |
|---|---|
| `mapping.py` | `create_core_mapping()` 三种策略（random/topology/community）将神经元分配到物理 core |
| `packet_trace.py` | `spike_trace_to_packet_trace()` 脉冲时间→packet trace DataFrame |
| `traffic_table.py` | `packet_trace_to_hardcoded_traffic_lines()` / `packet_trace_to_traffic_table()` packet trace→Noxim 流量文件 |

#### 仿真层

| 文件 | 核心功能 |
|---|---|
| `noxim_wrapper.py` | `run_noxim_with_hardcoded_traffic()` 子进程调用 Noxim，捕获输出 |
| `parse_noxim_output.py` | 从 Noxim stdout 或 JSON stats 文件提取延迟/吞吐/能耗指标 |

#### 指标与编排

| 文件 | 核心功能 |
|---|---|
| `noc_proxy_metrics.py` | `compute_noc_proxy_metrics()` 用曼哈顿距离快速估算 hop/energy/hotspot |
| `noc_experiment.py` | `run_single_noc_validation()` 编排完整 NoC 验证流水线 |

---

### 5.6 `experiments/` —— 实验入口

| 周次 | 脚本 | 实验内容 | 核心输出 |
|---|---|---|---|
| Week1 | `run_week1_toolchain_check.py` | 工具链完整性检查 | `backend_check.json`, `loihi_demo_summary.json` |
| Week2 | `run_graph_baseline.py` | 图生成 + Dijkstra 基线 | `graph.json`, `dijkstra_results.csv`, `example_path.png` |
| Week3 | `run_loihi_wavefront.py` | Loihi SNN 波前 vs 参考算法 | `wavefront_results.csv`, `spike_trace_pair_0.csv` |
| Week4 | `run_stdp_path_reconstruction.py` | STDP 路径重建 vs Dijkstra | `stdp_path_results.csv`, `pair_0_stdp_trace.csv` |
| Week5 | `run_dynamic_start_and_relay.py` | 动态起点 + 边阻塞/惩罚重规划 | `dynamic_start_results.csv`, `blocked_edge_results.json` |
| Week6 | `run_noc_validation.py` | 多 mapping 策略 NoC 性能对比 | `noc_results.csv`, `fig_average_hop_by_mapping.png` |

---

## 六、SNN 波前路由原理（图解）

```
图结构:
  0 ──(delay=3)──▶ 2
  │                │
  (delay=1)        (delay=1)
  │                │
  ▼                ▼
  1 ──(delay=1)──▶ 3

起点 = 0，目标 = 3
```

| 时刻 | 事件 |
|---|---|
| t=0 | 输入脉冲注入神经元 0，神经元 0 发放 |
| t=1 | 脉冲经 delay=1 到达神经元 1，神经元 1 发放 |
| t=2 | 脉冲从 1 经 delay=1 到达神经元 3，**神经元 3 首次发放** ✓ |
| t=3 | 脉冲从 0 经 delay=3 到达神经元 2，神经元 2 发放 |
| t=4 | 脉冲从 2 经 delay=1 到达神经元 3（已发放，忽略） |

**结果**：目标首次发放时间 = t=2，对应最短路径 0→1→3（总延迟=2）。

---

## 七、关键设计决策汇总

| 决策 | 值 | 原因 |
|---|---|---|
| 不应期 | 1000ms | > 最大路径延迟，每个神经元只发一次（最早到达 = 最短路径） |
| decay_v | 0 | 纯积分模式，不泄漏，保证可靠传播 |
| weight | 1.1 | > threshold，单次前驱脉冲即可触发后神经元 |
| dt_ms | 1 | 离散时间步 = 整数毫秒，贴近 Loihi 硬件整数时间 |
| tolerance_ms | 1.0 | 父节点时间匹配容差 |

---

## 八、运行方式

```bash
# 环境
conda create -n neuromorphic_noc python=3.10 -y
conda activate neuromorphic_noc
pip install -r requirements.txt

# Week1 - 工具链检查
python experiments/run_week1_toolchain_check.py

# Week2 - Dijkstra 基线
python experiments/run_graph_baseline.py --config configs/graph.yaml --output results/week2

# Week3 - Loihi 波前
python experiments/run_loihi_wavefront.py --graph results/week2/graph.json --config configs/brian2loihi.yaml --output results/week3

# Week4 - STDP 路径重建
python experiments/run_stdp_path_reconstruction.py --graph results/week2/graph.json --config configs/brian2loihi.yaml --output results/week4

# Week5 - 动态起点与重规划
python experiments/run_dynamic_start_and_relay.py --graph results/week2/graph.json --config configs/brian2loihi.yaml --output results/week5

# Week6 - NoC 验证（需要编译安装 Noxim）
python experiments/run_noc_validation.py --graph results/week2/graph.json --loihi-config configs/brian2loihi.yaml --noc-config configs/noxim.yaml --output results/week6
```
