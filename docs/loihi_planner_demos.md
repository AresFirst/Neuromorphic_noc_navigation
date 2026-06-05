# loihi_planner Demo 详解

本文档解释 `loihi_planner` 中几个 Loihi/Brian2Loihi demo 的设计目的、网络结构、关键参数、预期结果，以及它们和正式 `run_loihi_wavefront()` 波前路由过程之间的关系。当前项目保留 `loihi_planner/` 作为成熟实现，同时通过 `src/nmn/loihi/` 提供标准包 wrapper。

相关文件：

- `loihi_planner/loihi_lif_demo.py`
- `loihi_planner/loihi_delay_demo.py`
- `loihi_planner/loihi_small_wavefront_demo.py`
- `loihi_planner/loihi_wavefront.py`
- `loihi_planner/_brian2_runner.py`
- `loihi_planner/backend_check.py`
- `src/nmn/loihi/backend.py`
- `src/nmn/loihi/wavefront.py`
- `src/nmn/loihi/parent_trace.py`
- `src/nmn/loihi/path_reconstruction.py`
- `src/nmn/loihi/path_compare.py`

## 当前项目中的位置

Loihi/Brian2Loihi 是当前城市道路导航软件层的规划核心之一：

```text
MoST / SUMO 或 synthetic graph
    -> 临时 networkx.DiGraph
    -> delay_ms 编码
    -> run_loihi_wavefront()
    -> infer_parent_trace_from_spikes()
    -> reconstruct_path_from_parent()
    -> 路径比较或 SUMO route 反映射
```

在 MoST/SUMO 原始几何 overlay 入口中，`run_loihi_wavefront()` 只负责计算路径传播；最终地图显示由 `src/nmn/sumo/visualization.py` 使用 SUMO lane/edge geometry 完成。`networkx.DiGraph` 仍是计算图，不是最终地图格式。

NoC / Noxim 可以消费 wavefront 相关结果做可选验证，但不是城市道路软件层导航的必需步骤。

## 总体定位

正式的 `run_loihi_wavefront()` 会把一个 `networkx.DiGraph` 转换成 Loihi 风格的脉冲神经网络：

- 图节点 -> LIF 神经元
- 有向边 -> 兴奋性突触
- 边权重 `delay_ms` -> 突触传导延迟
- 起点节点 -> 在 `t=0` 注入一个输入脉冲
- 节点首次发放时间 -> 从起点到该节点的最早到达时间
- 目标节点首次发放时间 -> 从起点到目标的最短延迟

这个过程依赖三个基础事实：

1. 单个 Loihi 风格 LIF 神经元能被一次足够强的输入脉冲可靠触发。
2. 突触延迟在仿真中能准确反映整数毫秒级的边延迟。
3. 多条路径竞争时，目标神经元的首次发放时间对应最短延迟路径。

三个 demo 正好按这个依赖链逐层验证：

| Demo | 验证层级 | 覆盖的问题 |
|---|---|---|
| `loihi_lif_demo.py` | 单神经元 | 输入脉冲是否能触发 LIF 神经元发放 |
| `loihi_delay_demo.py` | 单边链路 | 突触延迟是否等于图边延迟 |
| `loihi_small_wavefront_demo.py` | 小图网络 | 多路径波前传播是否产生正确最早到达时间 |
| `loihi_wavefront.py` | 正式实现 | 任意复杂图上的通用波前路由 |

可以把它们理解成正式 wavefront 的分解测试：

```text
单神经元可发放
    -> 单条边延迟准确
        -> 小图中最短路径波前正确
            -> 任意 NetworkX 图可转成 SNN 并运行
```

## 后端模式

这些 demo 和正式 wavefront 都通过 `_brian2_runner.py` 加载 Brian2Loihi 后端。当前项目兼容两类后端模式。

### object_api 模式

这是当前环境中实际使用的模式，对应 `brian2_loihi` 包暴露的对象 API：

- `LoihiSpikeGeneratorGroup`
- `LoihiNeuronGroup`
- `LoihiSynapses`
- `LoihiSpikeMonitor`
- `LoihiNetwork`

object API 更接近 Loihi 抽象，神经元阈值和突触权重使用整数表示。例如 demo 中常见配置：

```python
threshold_v_mant=100
synapses.w = np.array([120], dtype=int)
```

这里 `120 > 100`，所以一次突触前脉冲就能让突触后神经元超过阈值并发放。

### brian2_device 模式

这是兼容旧 Brian2 设备接口的路径，使用标准 Brian2 对象：

- `SpikeGeneratorGroup`
- `NeuronGroup`
- `Synapses`
- `SpikeMonitor`
- `Network`

在这个模式下，阈值和权重使用浮点值：

```python
threshold="v > 1.0"
on_pre="v_post += 1.1"
```

这里 `1.1 > 1.0`，同样保证一次输入脉冲足以触发突触后神经元。

## Demo 1: loihi_lif_demo.py

### 目的

`run_loihi_lif_demo()` 是最底层的硬件/后端 sanity check。它只验证一件事：

> 一个 Loihi 风格 LIF 神经元能否接收输入脉冲，并至少发放一次。

如果这个 demo 失败，后面的延迟传播、波前路由、路径重建都没有继续分析的意义，因为基础神经元模型已经不能工作。

### 网络结构

该 demo 的网络极小：

```text
Input spike generator
        |
        | weight=120, delay=0
        v
LIF neuron 0
```

输入脉冲生成器在 `t=0` 发放一个脉冲，突触直接连接到唯一的 LIF 神经元。

### object_api 实现要点

核心对象：

```python
input_group = loihi.LoihiSpikeGeneratorGroup(
    1,
    np.array([0], dtype=int),
    np.array([0], dtype=int),
)

neurons = loihi.LoihiNeuronGroup(
    1,
    refractory=10,
    threshold_v_mant=100,
    decay_v=0,
    decay_I=4096,
)

synapses = loihi.LoihiSynapses(input_group, neurons, delay=0)
synapses.connect(i=np.array([0]), j=np.array([0]))
synapses.w = np.array([120], dtype=int)
```

关键参数含义：

- `threshold_v_mant=100`：发放阈值。
- `synapses.w=120`：突触权重，高于阈值，保证一次输入即可触发。
- `decay_v=0`：膜电位不泄漏，接近纯积分模式。
- `decay_I=4096`：电流慢衰减，在这个短 demo 中近似可靠保持输入效应。
- `refractory=10`：发放后进入不应期，防止短时间内多次发放。
- `network.run(5)`：运行 5 个离散 time step，足够观察一次发放。

### brian2_device 实现要点

兼容模式使用标准 LIF 方程：

```python
model="dv/dt = -v / (10*ms) : 1"
threshold="v > 1.0"
reset="v = 0"
on_pre="v_post += 1.1"
```

这条路径的核心仍然是：突触前输入让 `v_post` 增加 `1.1`，超过阈值 `1.0`，因此神经元发放。

### 返回结果

返回字典字段：

| 字段 | 含义 |
|---|---|
| `backend` | 实际使用的后端名称 |
| `num_spikes` | 监测到的神经元发放次数 |
| `spike_times_ms` | 发放时间列表 |
| `success` | 是否至少发放一次 |
| `error` | 错误信息 |

当前环境中的实际输出示例：

```python
{
    "backend": "brian2_loihi",
    "num_spikes": 1,
    "spike_times_ms": [0.0],
    "success": True,
    "error": None,
}
```

### 和正式 wavefront 的关系

正式 `run_loihi_wavefront()` 中，每个图节点都会变成一个 Loihi LIF 神经元。所有路径传播都依赖同一个基础动作：

```text
前驱神经元发放
    -> 突触传来兴奋输入
        -> 后继神经元超过阈值
            -> 后继神经元发放
```

`loihi_lif_demo.py` 只验证这个动作的最后半段：输入是否能触发一个神经元发放。

它对应正式 wavefront 中的这些代码思想：

- 创建 `LoihiNeuronGroup`
- 创建输入脉冲源
- 创建输入突触
- 设置权重大于阈值
- 用 `LoihiSpikeMonitor` 记录发放

## Demo 2: loihi_delay_demo.py

### 目的

`run_loihi_delay_demo(delay_ms=5)` 验证单条边的突触延迟是否正确。正式 wavefront 的核心假设是：

```text
后继节点发放时间 = 前驱节点发放时间 + 边延迟
```

如果单条边延迟都不准确，那么波前到达时间就不能代表路径代价。

### 网络结构

该 demo 使用两个神经元：

```text
Input spike generator
        |
        | weight=120, delay=0
        v
neuron 0
        |
        | weight=120, delay=delay_ms
        v
neuron 1
```

其中：

- `neuron 0` 是前驱神经元。
- `neuron 1` 是后继神经元。
- `delay_ms` 是希望验证的图边延迟。

默认 `delay_ms=5`，预期：

```text
neuron 0 在 t=0 发放
neuron 1 在 t=5 发放
observed_delay_ms = 5
```

### object_api 中的 delay - 1 补偿

当前 `brian2_loihi` object API 中，突触传导存在一个 1 ms 的调度/轴突偏移。为了让“图上的 delay_ms”和“观测到的发放时间差”一致，代码中使用：

```python
graph_synapses = loihi.LoihiSynapses(
    neurons,
    neurons,
    delay=max(0, int(delay_ms) - 1),
)
```

这意味着：

```text
LoihiSynapses.delay = 图边 delay_ms - 1
```

最终观测到：

```text
post_spike_time - pre_spike_time ~= delay_ms
```

这个补偿也被正式 `run_loihi_wavefront()` 采用。

### 为什么要求 delay_ms >= 1

函数开头会拒绝小于 1 的延迟：

```python
if delay_ms < 1:
    return {"success": False, "error": "delay_ms must be a positive integer."}
```

原因是项目中的图边延迟代表正的传播时间。正式图生成器也会把边延迟映射到正整数毫秒范围，例如 `[1, 10]`。

### 返回结果

返回字典字段：

| 字段 | 含义 |
|---|---|
| `pre_spike_times_ms` | 前驱神经元发放时间 |
| `post_spike_times_ms` | 后继神经元发放时间 |
| `observed_delay_ms` | 实测延迟 |
| `success` | 实测延迟是否与配置延迟匹配 |
| `error` | 错误信息 |

当前环境中的实际输出示例：

```python
{
    "pre_spike_times_ms": [0.0],
    "post_spike_times_ms": [5.0],
    "observed_delay_ms": 5.0,
    "success": True,
    "error": None,
}
```

### 和正式 wavefront 的关系

正式 wavefront 中，每条图边 `(u, v)` 都会变成一条突触：

```text
u 神经元 --delay_ms--> v 神经元
```

`loihi_delay_demo.py` 只验证一条边：

```text
0 --delay_ms--> 1
```

但这正是正式过程的最小单元。如果这个最小单元满足：

```text
t(v) = t(u) + delay(u, v)
```

那么多边路径就会自然满足：

```text
t(path end) = delay(e1) + delay(e2) + ... + delay(en)
```

因此 delay demo 是正式 wavefront “路径代价等于脉冲到达时间”这个核心假设的直接验证。

## Demo 3: loihi_small_wavefront_demo.py

### 目的

`run_loihi_small_wavefront_demo()` 是从单神经元、单边链路过渡到完整波前传播的中间验证。它在一个固定的 5 节点图上检查：

1. 起点脉冲是否能沿多条边传播。
2. 不同延迟路径是否会形成不同到达时间。
3. 目标节点的首次发放是否对应最短路径。

### 固定图结构

图中有 5 个节点，编号 `0` 到 `4`：

```text
0 --1--> 1 --1--> 3 --1--> 4
|                 ^
|                 |
3                 1
v                 |
2 ----------------+
```

边及延迟：

| 边 | 延迟 |
|---|---:|
| `0 -> 1` | 1 ms |
| `0 -> 2` | 3 ms |
| `1 -> 3` | 1 ms |
| `2 -> 3` | 1 ms |
| `3 -> 4` | 1 ms |

起点是 `0`，目标是 `4`。

### 路径竞争

从 `0` 到 `4` 至少有两条主要路径：

```text
路径 A: 0 -> 1 -> 3 -> 4
总代价: 1 + 1 + 1 = 3 ms

路径 B: 0 -> 2 -> 3 -> 4
总代价: 3 + 1 + 1 = 5 ms
```

由于神经元有较长不应期，而且首次发放代表最早到达，所以：

- `3` 会先被路径 `0 -> 1 -> 3` 在 `t=2` 激活。
- 稍后路径 `0 -> 2 -> 3` 到达时，`3` 已经发放过，不再改变首次发放时间。
- `4` 最终在 `t=3` 发放。

### 预期发放时间

理论上应得到：

| 神经元 | 首次发放时间 | 原因 |
|---|---:|---|
| `0` | 0 ms | 起点被输入脉冲直接触发 |
| `1` | 1 ms | `0 -> 1` 延迟 1 |
| `2` | 3 ms | `0 -> 2` 延迟 3 |
| `3` | 2 ms | `0 -> 1 -> 3` 总延迟 2，比经 `2` 更早 |
| `4` | 3 ms | `0 -> 1 -> 3 -> 4` 总延迟 3 |

当前环境中的实际输出示例：

```python
{
    "spike_times_by_neuron": {
        0: [0.0],
        1: [1.0],
        2: [3.0],
        3: [2.0],
        4: [3.0],
    },
    "target_arrival_time_ms": 3.0,
    "success": True,
    "error": None,
}
```

### 延迟分组

object API 路径中，小图 demo 把相同延迟的边分组：

```python
edges_by_delay = {
    1: [(0, 1), (1, 3), (2, 3), (3, 4)],
    3: [(0, 2)],
}
```

然后每组创建一个 `LoihiSynapses` 对象：

```python
for delay_ms, edges in edges_by_delay.items():
    synapses = loihi.LoihiSynapses(neurons, neurons, delay=max(0, delay_ms - 1))
    synapses.connect(i=sources, j=targets)
```

这和正式 `run_loihi_wavefront()` 中的做法一致。正式实现也是把图边按调整后的延迟分组，以减少 Synapses 对象数量。

### 和正式 wavefront 的关系

小图 demo 已经包含正式 wavefront 的大部分核心机制：

| 小图 demo 机制 | 正式 wavefront 对应机制 |
|---|---|
| 5 个固定节点 | 任意数量的 NetworkX 节点 |
| 手写边列表 | 遍历 `G.edges(data=True)` |
| 固定延迟 `{1, 3}` | 读取边属性 `delay_ms` |
| 起点固定为 `0` | 起点参数 `start` |
| 目标固定为 `4` | 目标参数 `target` |
| 手工分组 `edges_by_delay` | 自动构造 `delay_groups` |
| 运行 8 ms | 根据参考波前自动估计 `sim_time_ms` |
| 检查目标 `4` 是否在 3 ms 发放 | 检查任意目标是否发放 |

因此，小图 demo 是正式 wavefront 的“手工展开版”。它用最小但非平凡的图验证多路径竞争和最早到达原则。

## 正式过程: loihi_wavefront.py

### 函数入口

正式入口函数是：

```python
run_loihi_wavefront(
    G,
    start,
    target,
    delay_attr="delay_ms",
    sim_time_ms=None,
    threshold=1.0,
    weight=1.1,
    refractory_ms=1000,
    seed=0,
)
```

它输入一个有向图 `G`，输出每个可达节点的首次发放时间，以及目标是否到达。

### 输入图要求

`G` 是 `networkx.DiGraph`。项目中图一般由 `graph/complex_graph_generator.py` 生成。正式 wavefront 主要依赖这些信息：

- 节点 ID：可以是不连续整数，但当前返回结果会转成整数 ID。
- 边属性 `delay_ms`：正整数毫秒延迟。
- 边属性 `state`：如果为 `"blocked"`，该边会被跳过。

正式过程会忽略：

- `state="blocked"` 的边。
- 自环边，即 `source == target_node`。
- `delay <= 0` 的边。

### 步骤 1: 后端检查

正式函数首先调用：

```python
check_brian2loihi_available()
load_brian2loihi_backend()
```

这样做有两个目的：

1. 如果 Brian2Loihi 不可用，返回结构化错误，而不是让实验脚本崩溃。
2. 自动判断当前应该走 `object_api` 还是 `brian2_device`。

这和三个 demo 的开头完全一致。demo 不绕过后端检查，因此可以作为环境可用性的快速验证。

### 步骤 2: 输入合法性检查

正式函数会检查：

```python
if start not in G:
    return error
if target not in G:
    return error
```

demo 中节点是硬编码的，所以不需要这一步。正式函数要处理任意图，因此必须显式检查。

### 步骤 3: CPU 参考波前

正式函数会先运行：

```python
reference = event_driven_wavefront(G, start, target, delay_attr=delay_attr)
```

这个 CPU 版本不是替代 Loihi 结果，而是用于：

1. 计算目标的参考到达时间。
2. 自动估计一个足够但不过长的仿真时长。
3. 为后续测试和比较提供真值基础。

自动仿真时长由 `_build_sim_time_ms()` 给出：

```text
sim_time_ms = max(5, reference_arrival + max_delay + 5)
```

其中 `max_delay` 是非阻塞边的最大单边延迟。

小图 demo 直接写死 `network.run(8)`，正式函数则需要对任意图自动计算。

### 步骤 4: 图节点到神经元索引映射

NetworkX 图节点 ID 不一定连续，例如可能是：

```text
0, 5, 12, 31
```

但 Loihi 神经元组需要连续索引：

```text
0, 1, 2, 3
```

正式函数中使用：

```python
nodes = list(G.nodes())
node_index = {node: idx for idx, node in enumerate(nodes)}
```

之后所有边都通过 `node_index` 转换：

```text
图节点 source -> 神经元索引 node_index[source]
图节点 target -> 神经元索引 node_index[target]
```

demo 中节点本来就是 `0..N-1`，所以这个映射不明显；正式函数必须显式做。

### 步骤 5: 创建神经元组

object API 正式路径：

```python
neurons = loihi.LoihiNeuronGroup(
    len(nodes),
    refractory=refractory_steps,
    threshold_v_mant=max(1, int(round(float(threshold) * 64))),
    decay_v=0,
    decay_I=4096,
)
```

关键点：

- 每个图节点对应一个神经元。
- `threshold` 会转换成 Loihi 整数阈值。
- `decay_v=0` 让膜电位不泄漏，保证波前传播更像离散事件传播。
- `refractory_ms` 默认很大，使每个神经元只记录第一次到达。

注意当前 object API 路径中，正式函数内部使用整数权重 `120`。从设计上它对应 `weight > threshold` 的要求；配置项 `weight` 在 Brian2 device 路径中直接使用，在 object API 路径中等价体现为固定安全权重。

### 步骤 6: 起点注入

正式函数不直接把起点神经元膜电位设高，而是创建输入脉冲源：

```python
input_group = loihi.LoihiSpikeGeneratorGroup(
    1,
    np.array([0], dtype=int),
    np.array([0], dtype=int),
)
```

然后把它连接到起点神经元：

```python
input_synapses.connect(
    i=np.array([0], dtype=int),
    j=np.array([node_index[start]], dtype=int),
)
input_synapses.w = np.array([120], dtype=int)
```

这和 LIF demo、小图 demo 的输入方式一致。

### 步骤 7: 图边转突触

正式函数遍历所有边：

```python
for source, target_node, attrs in G.edges(data=True):
    if attrs.get("state") == "blocked":
        continue
    if source == target_node:
        continue
    delay = int(attrs.get(delay_attr, 0))
    if delay <= 0:
        continue
    adjusted_delay = max(0, delay - 1)
    delay_groups.setdefault(adjusted_delay, []).append(...)
```

这里有三个重要设计：

1. 阻塞边不参与传播。这让 Week 5 的 `RelayController.block_edge()` 能直接影响波前。
2. 延迟必须为正。这保持“路径代价 = 时间”的物理含义。
3. object API 使用 `delay - 1` 补偿。这一点由 `loihi_delay_demo.py` 验证。

### 步骤 8: 按延迟分组创建突触

正式函数不会每条边都创建一个 `LoihiSynapses`，而是按相同延迟分组：

```python
for adjusted_delay, edges in sorted(delay_groups.items()):
    synapses = loihi.LoihiSynapses(neurons, neurons, delay=adjusted_delay)
    synapses.connect(i=sources, j=targets)
    synapses.w = np.array([120] * len(edges), dtype=int)
```

这样做有两个好处：

1. 和 Loihi object API 的延迟模型更自然匹配。
2. 减少对象数量，对较大图更高效。

小图 demo 的 `edges_by_delay` 是这一步的手写版本。

### 步骤 9: 运行仿真并记录首次发放

正式函数创建 monitor：

```python
spike_monitor = loihi.LoihiSpikeMonitor(neurons)
```

运行：

```python
network.run(computed_sim_time_ms)
```

然后收集每个节点的首次发放时间：

```python
spike_times_by_neuron = {}
for neuron_index, spike_time in zip(spike_monitor.i, spike_monitor.t):
    node = nodes[int(neuron_index)]
    if node not in spike_times_by_neuron:
        spike_times_by_neuron[node] = float(spike_time)
```

只记录首次发放是关键，因为波前算法关心的是最短到达时间。如果后续更慢路径也到达同一个节点，它不应该覆盖更早路径。

### 返回值

正式函数返回：

| 字段 | 含义 |
|---|---|
| `backend` | 后端名称 |
| `start` | 起点 |
| `target` | 目标 |
| `spike_times_by_neuron` | `{原始节点 ID: 首次发放时间 ms}` |
| `target_arrival_time_ms` | 目标首次发放时间 |
| `num_spikes` | 总发放事件数 |
| `active_neurons` | 至少发放一次的节点数 |
| `sim_time_ms` | 实际仿真时长 |
| `success` | 目标是否发放 |
| `error` | 错误信息 |

## demo 和正式 wavefront 的逐层关系

### 1. LIF demo 验证神经元发放

正式过程中的每个节点都必须能被输入触发。LIF demo 证明：

```text
强输入 -> 神经元发放
```

这对应所有图节点的基本可激活性。

### 2. Delay demo 验证边延迟

正式过程中的每条边都依赖：

```text
u 在 t 发放
v 在 t + delay(u, v) 发放
```

Delay demo 证明单条边满足这个关系，并确定 object API 下需要 `delay - 1` 补偿。

### 3. Small wavefront demo 验证路径竞争

正式过程需要在多路径情况下选择最早到达路径。Small wavefront demo 证明：

```text
多条路径同时传播
    -> 较短延迟路径先到
        -> 目标首次发放时间等于最短路径代价
```

这就是正式 wavefront 的核心算法性质。

### 4. run_loihi_wavefront 泛化到任意图

正式函数把小图 demo 的手写结构泛化为：

- 任意 NetworkX 有向图。
- 任意起点/目标。
- 任意正整数边延迟。
- 自动跳过阻塞边。
- 自动计算仿真时长。
- 自动收集所有节点的首次发放时间。

## 与路径重建的关系

`run_loihi_wavefront()` 本身只负责产生发放时间：

```text
{node: first_spike_time}
```

它不直接返回完整路径。路径重建由后续模块完成：

```text
run_loihi_wavefront()
    -> spike_times_by_neuron
        -> infer_parent_trace_from_spikes()
            -> reconstruct_path_from_parent()
```

其中 `infer_parent_trace_from_spikes()` 会检查每条候选前驱边：

```text
spike_time[pred] + delay(pred, node) ~= spike_time[node]
```

如果匹配，就说明该前驱可能是让当前节点发放的父节点。再通过 parent 指针从目标反向追踪，就能得到 SNN 路径。

因此，三个 demo 虽然没有完整演示 parent trace，但它们确保了 parent trace 所依赖的时间关系是成立的。

## 建议运行方式

可以用当前 Brian2Loihi 环境直接运行：

```bash
/opt/anaconda3/envs/brian2loihi/bin/python - <<'PY'
from loihi_planner.loihi_lif_demo import run_loihi_lif_demo
from loihi_planner.loihi_delay_demo import run_loihi_delay_demo
from loihi_planner.loihi_small_wavefront_demo import run_loihi_small_wavefront_demo

print(run_loihi_lif_demo())
print(run_loihi_delay_demo(5))
print(run_loihi_small_wavefront_demo())
PY
```

新代码也可以通过 `nmn.loihi` wrapper 导入正式规划函数：

```python
from nmn.loihi import run_loihi_wavefront
from nmn.loihi import infer_parent_trace_from_spikes
from nmn.loihi import reconstruct_path_from_parent
```

也可以通过测试套件间接验证：

```bash
/opt/anaconda3/envs/brian2loihi/bin/python -m pytest tests/test_loihi_demos.py tests/test_loihi_wavefront.py
```

## 调试时如何使用这些 demo

如果正式 wavefront 出问题，建议按以下顺序排查：

1. 先跑 `run_loihi_lif_demo()`。
   如果失败，问题通常在 Brian2Loihi 安装、后端加载、基本神经元 API 或阈值/权重设置。

2. 再跑 `run_loihi_delay_demo(delay_ms=5)`。
   如果 LIF 成功但 delay 失败，重点检查突触 delay 语义、`delay - 1` 补偿、时间单位和 monitor 输出。

3. 再跑 `run_loihi_small_wavefront_demo()`。
   如果前两个成功但小图失败，重点检查多突触连接、延迟分组、refractory 设置和多路径竞争。

4. 最后跑正式 `run_loihi_wavefront()`。
   如果 demo 都成功但正式图失败，问题更可能在图数据本身，例如节点 ID 映射、边属性缺失、`state="blocked"`、不可达目标、仿真时长不足或路径重建逻辑。

## 小结

三个 demo 不是孤立示例，而是正式 wavefront 的分层验证：

- `loihi_lif_demo.py` 验证“神经元能发放”。
- `loihi_delay_demo.py` 验证“突触延迟等于边延迟”。
- `loihi_small_wavefront_demo.py` 验证“多路径波前的首次到达等于最短路径代价”。
- `loihi_wavefront.py` 把这些机制扩展到任意复杂图，并作为后续 parent trace、路径重建、动态重规划、SUMO route 反映射和可选 NoC packet trace 的输入基础。
