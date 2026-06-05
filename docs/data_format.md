# 数据格式说明

本文档说明当前项目使用的主要数据格式：标准图 JSON、SUMO 原始几何、MoST/SUMO overlay 路径、动态导航输出、Spike trace 和可选 NoC packet trace。

## 标准 `graph.json`

项目的 graph-level 实验使用 `graph.graph_io.save_graph_json()` 保存 `networkx.DiGraph`：

```json
{
  "directed": true,
  "multigraph": false,
  "graph": {},
  "nodes": [],
  "edges": []
}
```

节点记录：

```text
id: int | str
x: float
y: float
region: int
source: str
original_id: str
sumo_node_id: str
```

常用含义：

- `id`：计算图节点 ID。MoST 标准化后通常是整数。
- `x`、`y`：二维坐标。
- `region`：区域编号，用于分区或可视化。
- `source`：数据来源，例如 `synthetic`、`most_raw`、`sumo`。
- `original_id` / `sumo_node_id`：原始地图节点 ID，用于反查。

边记录：

```text
source: int | str
target: int | str
distance: float
base_cost: float
delay_ms: int
original_delay_ms: int
state: str
original_edge_id: str
sumo_edge_id: str
merged_sumo_edge_ids: list[str]
lane_ids: list[str]
shape: list[list[float]]
```

常用含义：

- `source`、`target`：图边端点。
- `distance`：几何距离或 lane 平均长度。
- `base_cost`：用于路径比较的基础代价，可为距离或旅行时间。
- `delay_ms`：SNN wavefront 使用的整数传播延迟。
- `original_delay_ms`：初始延迟，动态拥塞会修改 `delay_ms`。
- `state`：边状态。
- `original_edge_id` / `sumo_edge_id`：原始 SUMO edge ID。
- `merged_sumo_edge_ids`：同一端点之间多条 SUMO edge 合并时保留的 ID 列表。
- `lane_ids`：对应 SUMO lane ID。
- `shape`：SUMO lane/edge polyline，供路径反映射和 overlay 使用。

`graph_io` 会处理边属性中名为 `source` / `target` 的保留字段冲突；冲突属性会放进 `__attrs__`，读取时恢复。

## 边状态

当前动态导航主要使用：

```text
normal
congested
blocked
penalized
```

含义：

- `normal`：正常通行。
- `congested`：拥塞，通常表现为 `delay_ms` 变大。
- `blocked`：阻断，动态规划时不可通行。
- `penalized`：保留状态，用于惩罚但不完全阻断的边。

## SUMO 原始几何

`src/nmn/sumo/geometry.py` 直接读取 SUMO `.net.xml`，并保留用于最终可视化的原始结构：

```text
SumoMapGeometry
├── netxml_path: str
├── nodes: dict[str, SumoNodeGeometry]
└── edges: dict[str, SumoEdgeGeometry]
```

节点：

```text
node_id: str
x: float
y: float
node_type: str | None
```

边：

```text
edge_id: str
from_node: str | None
to_node: str | None
function: str | None
lanes: tuple[SumoLaneGeometry, ...]
shape: tuple[tuple[float, float], ...]
```

lane：

```text
lane_id: str
index: int
speed: float | None
length: float | None
shape: tuple[tuple[float, float], ...]
```

重要约束：`SumoMapGeometry` 是显示层来源。`networkx.DiGraph` 只能作为计算层，不能作为最终地图格式。

## MoST/SUMO overlay 路径

`experiments/run_most_sumo_overlay_navigation.py` 会生成：

```text
results/most_sumo_overlay/sumo_route.json
```

格式：

```json
{
  "graph_path": [128, 115, 43],
  "sumo_node_ids": ["142855", "..."],
  "sumo_edge_ids": ["-152606#4", "153100"],
  "segments": []
}
```

每个 `segments` 元素：

```text
graph_source: int | str
graph_target: int | str
sumo_edge_id: str
from_sumo_node_id: str
to_sumo_node_id: str
lane_ids: list[str]
shape: list[list[float]]
delay_ms: int
base_cost: float
```

这个文件是从 SNN 输出回到 SUMO/MoST 坐标和道路 ID 的关键桥梁。

## MoST/SUMO overlay 总结

```text
results/most_sumo_overlay/planning_summary.json
```

关键字段：

```text
success: bool
netxml_path: str
sumocfg_path: str | null
sumo_load_check: dict | null
backend_check: dict
start: int
target: int
start_sumo_node_id: str
target_sumo_node_id: str
graph_is_temporary: true
visualization_source: "original_sumo_geometry"
sumo_edge_ids: list[str]
route_overlay_png: str
```

验证点：

- `graph_is_temporary` 必须为 `true`。
- `visualization_source` 必须是 `original_sumo_geometry`。
- 输出图片必须来自 SUMO lane/edge polyline overlay，而不是 NetworkX 节点散点图。

## Dynamic City Navigation 输出

`experiments/run_dynamic_city_navigation.py` 输出：

```text
results/dynamic_city_navigation/dynamic_step_logs.csv
results/dynamic_city_navigation/dynamic_summary.json
results/dynamic_city_navigation/congestion_events.json
results/dynamic_city_navigation/final_route.json
results/dynamic_city_navigation/frames/
results/dynamic_city_navigation/preview_final.png
```

`dynamic_step_logs.csv` 常用字段：

```text
step
current_node
target_node
route
replanned
active_congested_edges
```

`congestion_events.json` 描述拥塞事件：

```text
edge_u: int
edge_v: int
start_step: int
end_step: int
delay_factor: float
threshold_penalty: float
mode: str
```

## Spike trace

SNN wavefront 输出中的核心结构是：

```text
spike_times_by_neuron: dict[int, float]
target_arrival_time_ms: float | null
num_spikes: int
success: bool
```

含义：

- key 是神经元/图节点 ID。
- value 是首次发放时间，单位 ms。
- parent trace 根据 `spike_time[pred] + delay(pred, node) ~= spike_time[node]` 反推出路径。

## 可选 NoC packet trace

NoC / Noxim 不是城市道路软件导航主线。需要验证 NoC 时，packet trace 使用：

```text
cycle
src_neuron
dst_neuron
src_core
dst_core
packet_type
packet_size
```

其中 `src_core` / `dst_core` 来自 NoC core mapping，`cycle` 是仿真周期。
