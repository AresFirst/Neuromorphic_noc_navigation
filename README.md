# Neuromorphic OSM SNN Navigation

这是一个“真实道路地图 + SNN 路径规划 + Web GUI 可视化”的精简项目。

当前主线不再使用 SUMO，也不再依赖 MoST 数据集。地图来自 OpenStreetMap，使用 OSMnx 下载和缓存；计算层临时转换成 `networkx.DiGraph`；规划层使用 Brian2Loihi wavefront 或 CPU-compatible wavefront；最终结果在 Streamlit + Folium Web 页面中显示。

## 数据流

```text
OpenStreetMap / OSMnx
    -> networkx.MultiDiGraph
    -> 项目 DiGraph
       - 合并平行边
       - 保留 OSM node id、经纬度、道路 geometry
       - 生成 SNN neuron / synapse 映射
    -> 可选 simulated traffic overlay
       - 拥堵边提高 cost / delay_ms
       - 阻塞边 state = blocked
       - 拥堵路口转换为 node inhibition penalty
    -> SNN wavefront spike propagation
    -> parent trace / STDP-like 路径回溯
    -> NavigationResult
    -> Streamlit + Folium GUI
       - 真实底图
       - 道路网络
       - 起点/终点
       - wavefront 激活节点和边
       - 最终路径
       - 小车位置
```

`networkx.DiGraph` 只作为计算层使用，不作为最终地图显示格式。GUI 中的道路显示始终基于 OSM 道路几何。

## 项目结构

```text
.
├── app.py                         # Streamlit 入口
├── app_demo.py                    # 独立 demo，便于快速试验
├── configs/
│   └── brian2loihi.yaml           # SNN 参数
├── loihi_planner/                 # Brian2Loihi wavefront 与路径回溯
├── src/
│   ├── gui/
│   │   └── app.py                 # Web GUI 主实现
│   ├── maps/
│   │   ├── graph_adapter.py       # OSMnx MultiDiGraph -> 项目 DiGraph
│   │   └── osmnx_loader.py        # OSM 下载、缓存、加载
│   ├── navigation/
│   │   ├── planner.py             # SNN planner -> NavigationResult
│   │   └── result.py              # 标准结果结构
│   ├── snn/
│   │   └── planner.py             # Brian2Loihi/CPU wavefront 入口
│   ├── traffic/
│   │   ├── simulator.py           # 模拟交通、拥堵叠加、动态图生成
│   │   └── state.py               # TrafficSnapshot 数据结构
│   └── nmn/loihi/                 # 兼容导出
└── tests/
    ├── test_graph_adapter.py
    ├── test_gui_app.py
    ├── test_navigation_planner.py
    └── test_traffic_simulator.py
```

## 核心代码文件用途

### 入口文件

- `app.py`

  Web GUI 的根入口。用户运行：

  ```bash
  streamlit run app.py
  ```

  时，实际会进入 `src/gui/app.py` 中的 `main()`。这个文件只负责把项目根目录和 `src/` 加入 Python import 路径，并转发到正式 GUI。

- `app_demo.py`

  独立实验 demo。它不走当前项目的完整模块化 pipeline，而是在一个文件里直接完成 OSMnx 下载、Brian2 wavefront、Folium 绘图和 Streamlit 页面展示。它适合用来快速检查环境是否能跑通，但正式功能以 `app.py` 和 `src/gui/app.py` 为准。

- `build_backend.py`

  轻量级本地构建后端，用于支持：

  ```bash
  pip install -e .
  ```

  它不参与导航算法，只是让项目在离线或最小依赖环境下也能以 editable 方式安装。

### GUI 层

- `src/gui/app.py`

  当前 Web 页面主实现。负责：

  - Streamlit 侧边栏参数输入。
  - OSM 地图加载按钮。
  - bbox / place name 输入。
  - 起点和终点经纬度输入。
  - 起终点 snap 到最近 OSM 道路节点。
  - 调用 `run_navigation()` 执行 SNN wavefront。
  - Folium 地图绘制。
  - 普通道路、最终路径、wavefront、交通拥堵、小车 marker 的 overlay。
  - wavefront timestep slider。
  - car position slider。
  - 模拟交通 `Step Traffic + Replan` 动态重规划。
  - 页面底部指标和 JSON 调试信息。

  这个文件是用户实际交互最多的地方，也是把地图、SNN、交通和可视化串起来的闭环入口。

### 地图层

- `src/maps/osmnx_loader.py`

  负责真实道路地图加载。它支持两种输入：

  - `place_name`：例如 `Shinjuku, Tokyo, Japan`。
  - `BoundingBox`：手动指定 `north / south / east / west`。

  它的主要职责是：

  - 调用 OSMnx 从 OpenStreetMap 下载道路网络。
  - 给道路边添加 speed 和 travel time。
  - 下载后保存为 GraphML 缓存。
  - 下次加载相同区域时优先读取本地缓存。
  - 在 OSMnx 或地理库不可用时，尝试使用手写 Overpass fallback。

  这个模块输出的是 OSMnx 风格的 `networkx.MultiDiGraph`，仍然保留 OSM 原始节点、边和道路属性。

- `src/maps/graph_adapter.py`

  负责把 OSMnx 的 `MultiDiGraph` 转成项目内部使用的 `DiGraph`。这是地图到 SNN pipeline 的关键转换层。

  它做的事情包括：

  - 把 OSM node id 映射为连续的项目 node id。
  - 当前实现中，项目 node id 也等于 `snn_neuron_index`。
  - 保留 `original_osm_node_id`、`lat / lon`、`x / y`。
  - 合并平行边，同一 `(u, v)` 只保留 cost 最小的一条。
  - cost 优先使用 `travel_time`，其次使用 `length`，最后使用 `1.0`。
  - 生成 `delay_ms` 作为 SNN 突触延迟。
  - 保留道路 `geometry`，用于 Folium 绘制真实道路形状。
  - 提供 `path_nodes_to_latlon()`，把 SNN 输出路径转回地图坐标。
  - 提供 `nearest_node_by_latlon()`，把用户输入的经纬度 snap 到最近道路节点。

### 导航结果与规划层

- `src/navigation/result.py`

  定义标准输出数据结构：

  - `WavefrontFrame`
  - `NavigationResult`

  GUI、测试和后续扩展都应该基于这个结果结构，而不是直接依赖某个后端返回的原始字典。

- `src/navigation/planner.py`

  高层导航入口。它把 SNN wavefront 后端的输出整理成 `NavigationResult`。

  主要流程是：

  ```text
  DiGraph
      -> run_wavefront()
      -> spike_times_by_node
      -> infer_parent_trace_from_spikes()
      -> reconstruct_path_from_parent()
      -> NavigationResult
  ```

  它还负责：

  - Brian2Loihi 失败时自动降级到 CPU reference。
  - 根据 spike time 生成 wavefront frame。
  - 计算路径长度、旅行时间、总代价。
  - 把调试信息写入 `metadata`。

### SNN 与 Brian2Loihi 层

- `src/snn/planner.py`

  SNN wavefront 的薄封装。根据 `use_loihi` 决定：

  - 使用 `loihi_planner.run_loihi_wavefront()`。
  - 或使用 CPU-compatible `event_driven_wavefront()`。

  它的返回字段会保持一致，方便上层 `navigation/planner.py` 不关心具体后端。

- `loihi_planner/loihi_wavefront.py`

  Brian2Loihi wavefront 的核心实现。负责把 `DiGraph` 映射成 SNN：

  ```text
  graph node -> neuron
  directed edge -> synapse
  edge.delay_ms -> synaptic delay
  start node -> input spike
  goal node -> target neuron
  ```

  它会运行仿真并返回每个 neuron 的首次 spike time。

- `loihi_planner/wavefront_reference.py`

  CPU 参考 wavefront。它是一个 Dijkstra-like 的事件驱动传播算法，用来在没有 Brian2Loihi 时保持项目可运行，也用于验证 SNN wavefront 的行为。

- `loihi_planner/parent_trace.py`

  根据 spike time 和图拓扑推断每个 neuron 是被哪个前驱 neuron 激活的。这个 parent trace 用于从终点反向回溯路径。

- `loihi_planner/path_reconstruction.py`

  从 `parent_trace` 中重建：

  ```text
  start -> ... -> goal
  ```

  的正向路径节点序列。

- `loihi_planner/path_compare.py`

  路径代价计算工具。用于统计最终路径的 `cost`、`length` 或其他边属性总和。

- `loihi_planner/backend_check.py`

  检查当前环境中 Brian2 和 Brian2Loihi 是否可用，并返回版本和错误信息。

- `loihi_planner/_brian2_runner.py`

  Brian2Loihi 后端加载器。它负责兼容不同 Brian2Loihi 包名和运行模式。

- `loihi_planner/loihi_config.py`

  加载和规范化 Brian2Loihi 参数，例如 threshold、weight、refractory 和 seed。

### 模拟交通层

- `src/traffic/state.py`

  定义模拟交通状态：

  - `TrafficEdgeState`
  - `TrafficSnapshot`

  `TrafficSnapshot` 描述某个 traffic step 中哪些边拥堵、哪些边阻塞、哪些节点受到抑制。

- `src/traffic/simulator.py`

  负责生成模拟交通，并把交通状态叠加到地图图上。

  当前实现不是直接修改 Brian2Loihi 内部 neuron，而是在 `DiGraph` 层修改：

  - `cost`
  - `travel_time`
  - `delay_ms`
  - `state = "blocked"`
  - `node_penalty_ms`

  然后重新调用 SNN wavefront。这样可以形成：

  ```text
  拥堵变化
      -> 图代价变化
      -> SNN delay 变化
      -> wavefront 重新扩散
      -> 路径重新规划
  ```

### 兼容导出层

- `src/nmn/loihi/__init__.py`

  保留旧的 `nmn.loihi` 导入路径，实际实现委托给 `loihi_planner/`。如果旧代码里还有：

  ```python
  from nmn.loihi import run_loihi_wavefront
  ```

  仍然可以继续工作。

### 测试文件

- `tests/test_graph_adapter.py`

  测试 OSM 图适配逻辑，包括平行边合并、node id 与 neuron index 映射、路径坐标回映射、delay 上限编码。

- `tests/test_navigation_planner.py`

  测试完整导航 planner，包括 CPU wavefront、Loihi fallback、不可达目标时的 partial wavefront。

- `tests/test_gui_app.py`

  测试 GUI 侧的非渲染逻辑，例如有向可达性提示、任意 timestep wavefront 重建。

- `tests/test_traffic_simulator.py`

  测试模拟交通层，包括不污染 base graph、拥堵阻塞当前路径后触发 reroute。

## 环境安装

推荐使用当前 conda 环境：

```bash
conda activate neuro-nav
pip install -r requirements.txt
pip install -e .
```

如果 OSMnx 相关地理库安装慢，可以先用 conda-forge 安装：

```bash
conda activate neuro-nav
conda install -c conda-forge osmnx geopandas shapely pyproj folium streamlit streamlit-folium pytest
pip install -e .
```

## 启动 Web GUI

```bash
conda activate neuro-nav
streamlit run app.py
```

打开页面后的推荐流程：

1. 在侧边栏选择 `Map input`。
2. 使用 `Place name` 时输入城市/区域名，例如 `Shinjuku, Tokyo, Japan`。
3. 使用 `Bounding box` 时输入 `North / South / East / West` 四个边界坐标。
4. 选择 `Network type`，默认 `drive` 会保留真实机动车道路方向。
5. 点击 `Load OSM Map` 下载或加载缓存地图。
6. 输入 `Start latitude / Start longitude` 和 `Goal latitude / Goal longitude`。
7. 系统会把起点和终点 snap 到最近 OSM 道路节点。
8. 点击 `Run SNN Navigation`。
9. 查看 wavefront、最终路径、指标和小车位置。
10. 如果要模拟拥堵，打开 `Simulated traffic`，点击 `Step Traffic + Replan`。

## Web 页面坐标说明

### Place Name

`Place name` 是 OSMnx/Nominatim 使用的地名查询字符串。例如：

```text
Shinjuku, Tokyo, Japan
```

使用地名时，OSMnx 会自动查询该区域边界，然后下载该区域内的道路网络。地名越大，下载越慢，图越大，SNN 运行也越慢。

### Bounding Box

`Bounding box` 是一个矩形地图裁剪框，用四个经纬度边界定义：

- `North`：北边界，最大纬度 latitude。
- `South`：南边界，最小纬度 latitude。
- `East`：东边界，最大经度 longitude。
- `West`：西边界，最小经度 longitude。

纬度 latitude 控制南北方向，经度 longitude 控制东西方向。以东京新宿附近为例：

```text
North = 35.7040
South = 35.6810
East  = 139.7160
West  = 139.6850
```

这表示只加载：

```text
纬度 35.6810 到 35.7040
经度 139.6850 到 139.7160
```

注意：

- `North` 必须大于 `South`。
- `East` 必须大于 `West`，在日本、中国、美国本土等常见区域通常如此。
- bbox 越小，加载越快，页面越流畅。
- bbox 太小可能导致起点/终点落在断开的道路片段中，目标 neuron 不发放。

### Start / Goal Coordinates

页面里的：

- `Start latitude`
- `Start longitude`
- `Goal latitude`
- `Goal longitude`

不是直接作为 SNN 节点使用。系统会先把这些经纬度 snap 到最近的 OSM 道路节点，然后使用 snap 后的节点 ID 作为：

- 起点 node id
- 终点 node id
- 起点 neuron index
- 终点 neuron index

因此，如果你输入的坐标在道路旁边，实际起终点会落到最近道路节点。页面下方会显示 snapped 后的 `Start node` 和 `Goal node`。

## 地图中点、线、格点的含义

这个项目里的“格点”不是规则网格，也不是像棋盘那样均匀分布的点。它们来自真实 OSM 道路网络。

### 道路线

地图上的普通道路线是 OSM 道路几何：

- 灰色细线：普通道路网络。
- 红色粗线：SNN 规划出的最终路径。
- 青色线：当前 wavefront frame 中已经激活的边。

这些线对应图中的 directed edge，也对应 SNN 中的 synapse。边上保存：

- `length`：道路长度，单位通常是米。
- `travel_time`：估计通行时间。
- `cost`：路径规划代价，优先使用 `travel_time`。
- `delay_ms`：编码给 SNN wavefront 的突触延迟。

Brian2Loihi 对 delay 有上限，本项目会把 `delay_ms` 限制到 `1..62`，同时保留真实代价 `cost` 和 `raw_delay_ms`。

### 道路节点 / 图节点 / SNN 神经元

OSM 道路节点通常表示：

- 路口。
- 道路端点。
- 道路几何折点。
- OSM 数据中用于描述道路形状的节点。

项目转换后，每个图节点会对应一个 SNN neuron：

```text
OSM node id
    -> 项目 node id
    -> snn_neuron_index
```

节点保存：

- `original_osm_node_id`
- `lat / y`
- `lon / x`
- `snn_neuron_index`

所以地图上的激活点可以理解为：某个道路图节点对应的神经元在当前 wavefront 中已经发放 spike。

### Wavefront 激活点

当点击 `Run SNN Navigation` 后，起点 neuron 注入初始 spike。脉冲沿道路边传播，经过突触延迟后激活下一个 neuron。

GUI 中：

- 青色 CircleMarker：当前 timestep 之前已经发放过 spike 的 neuron。
- 橙色 CircleMarker：当前 timestep 新发放的 neuron。
- 青色 PolyLine：当前 timestep 之前已经传播完成的 edge/synapse。
- 橙色虚线 PolyLine：当前 timestep 正在传播中的 edge/synapse，即前驱 neuron 已发放，但延迟还没有结束。
- `Wavefront timestep (ms)`：按毫秒拖动的 wavefront 时间滑块，用于观察神经元逐步激活过程。
- `t=... ms`：当前 slider 对应的 SNN/CPU wavefront 时间。

如果 wavefront 只传播到 `t=1 ms`，那么 slider 最大值是 `1`，这是正常的：

```text
timestep 0 ms -> 起点 neuron 发放
timestep 1 ms -> 波前传播到下一批可达 neuron
```

是否到达终点不要看 slider 最大值，要看：

```json
"success": true
"target_arrival_time_ms": ...
```

如果：

```json
"success": false
"target_arrival_time_ms": null
```

说明目标 neuron 没有收到 spike。此时 wavefront 可能仍然有若干 frame，因为波前传播到了部分可达节点，但没有传播到目标。

### Start / Goal / Car

- 绿色 marker：snap 后的起点节点。
- 紫色 marker：snap 后的终点节点。
- 红色小车 marker：沿最终路径 polyline 的当前位置。
- `Car position` slider：只在存在最终路径时显示，用于手动移动小车。

第一版小车不是自动播放动画，而是由 slider 控制路径上的位置。

## 模拟交通拥堵与动态重规划

本项目不接入真实交通 API。Web GUI 中的 `Simulated traffic` 是一个可重复的模拟交通层，用来验证“拥堵改变 SNN wavefront 扩散路径”的闭环。

操作流程：

1. 先加载 OSM 地图。
2. 输入起点和终点。
3. 点击 `Run SNN Navigation`，得到一条初始路径。
4. 在侧边栏打开 `Simulated traffic`。
5. 调整交通参数。
6. 点击 `Step Traffic + Replan`。
7. 系统会生成一个新的 `TrafficSnapshot`，把部分拥堵优先放到当前路径附近，再重新运行 wavefront。
8. 如果存在更快路线，红色路径会发生变化。

交通参数含义：

- `Traffic vehicles`：模拟车辆数量。越大，热点道路越容易变拥堵。
- `Traffic hotspots`：每个 traffic step 生成多少条拥堵热点边。
- `Congestion strength`：拥堵对 `cost / travel_time / delay_ms` 的放大强度。
- `Block threshold`：拥堵超过该阈值时，该边会变为 `blocked`，wavefront 不再通过。
- `Node inhibition penalty ms`：拥堵路口给进入该节点的边增加多少额外 delay，等效于提高对应 neuron 的发放难度。
- `Traffic seed`：随机种子。相同 seed 和 step 会产生可重复的拥堵。
- `Traffic edges to draw`：最多绘制多少条交通状态边，用于控制性能。

模拟交通如何影响 SNN：

```text
轻微拥堵 edge
    -> cost 增加
    -> travel_time 增加
    -> delay_ms 增加

严重拥堵 edge
    -> state = blocked
    -> wavefront 跳过这条边

拥堵 node / intersection
    -> 给进入该 node 的边增加 node_penalty_ms
    -> 等效为该 node 对应 neuron 更难被激活
```

地图颜色：

- 黄色线：轻微拥堵。
- 橙色线：中等拥堵。
- 红色线：严重拥堵。
- 深红虚线：blocked edge。
- 紫红色圆点：被拥堵抑制的 node/neuron。

注意：模拟交通不会修改原始 OSM 图。每次 traffic step 都从 `base_graph` 重新叠加交通状态，生成临时 `planning_graph`。这样可以避免 delay 多次累加导致图越来越慢。

## Web 性能与卡顿处理

Streamlit 的交互模型是：每次拖动 slider 都会重新运行页面脚本。Folium 地图也是重新生成一个 HTML/Leaflet 地图。因此，当道路边很多、激活点很多时，拖动 `Car position` 或 `Wavefront timestep (ms)` 会卡顿。

本项目已做的优化：

- 地图道路几何在加载 OSM 图后预计算，并保存在 `st.session_state` 中。
- Folium 使用 `prefer_canvas=True`，大量线段会尽量走 canvas 渲染。
- `st_folium(..., returned_objects=[])`，减少前端返回对象带来的开销。
- 侧边栏提供 `Draw base roads`，可以临时关闭普通道路底图，只显示路径、wavefront 和 marker。
- 侧边栏提供 `Road edges to draw`，限制普通道路绘制数量。
- 侧边栏提供 `Wavefront nodes to draw`，限制激活 neuron 点数量。
- 侧边栏提供 `Traffic edges to draw`，限制拥堵边绘制数量。

推荐设置：

```text
Road edges to draw      = 800 到 1500
Wavefront nodes to draw = 300 到 800
Draw base roads         = 关闭后拖动小车最快
Bounding box            = 尽量只覆盖需要的区域
```

如果只是观察小车沿路径移动，可以关闭 `Draw base roads`。如果只是观察 SNN 扩散，可以降低 `Road edges to draw`，保留 wavefront 点和边。

## 有向道路与不可达问题

默认 `network_type="drive"` 会保留真实机动车道路方向，包含单行道限制。因此可能出现：

```text
No directed route exists from start to goal,
but the reverse direction is reachable.
```

这表示：

- 从当前起点到终点没有有向路径。
- 但从终点到起点存在路径。
- 常见原因是起终点 snap 到了单行道方向相反的位置。

这种情况下目标 neuron 不会发放 spike，是正确行为。可以尝试：

- 交换起点和终点。
- 把起点或终点坐标移动到附近路口。
- 改用 `network_type=all` 后重新加载地图。
- 扩大 bbox。
- 避免把起终点放在高架、匝道、封闭小路或单行道路段的错误方向。

## OSM 地图缓存

首次下载地图后会保存到：

```text
data/osm_cache/*.graphml
```

后续加载相同 place/bbox 会优先使用本地缓存。若 OSM 下载失败，请检查网络、缩小 bbox，或复用已有 GraphML 缓存。

## NavigationResult

`src/navigation/result.py` 定义统一输出：

```python
WavefrontFrame(
    t: int,
    active_nodes: list[int],
    active_edges: list[tuple[int, int]],
)

NavigationResult(
    start_node: int,
    goal_node: int,
    path_nodes: list[int],
    path_edges: list[tuple[int, int]],
    wavefront_frames: list[WavefrontFrame],
    total_cost: float | None,
    metadata: dict,
)
```

常见 metadata 字段：

- `success`：是否找到最终路径。
- `backend`：实际使用的后端，例如 `cpu_reference`。
- `loihi_error`：Brian2Loihi 后端失败时保留的错误信息。
- `target_arrival_time_ms`：目标 neuron 首次发放时间。
- `path_length_m`：最终路径长度。
- `path_travel_time_s`：最终路径估计通行时间。
- `wavefront_steps`：GUI 中可视化的 wavefront frame 数。
- `wavefront_time_max_ms`：GUI 中 `Wavefront timestep (ms)` 的最大时间。
- `spike_times_by_node`：每个 node/neuron 的首次发放时间，用于按 timestep 重建 wavefront 状态。

若 Brian2Loihi 后端不可用，导航层会自动降级到 CPU-compatible wavefront，以保证 Web 闭环仍然可以运行。

## 测试

```bash
conda activate neuro-nav
python -m pytest -q
```

当前测试覆盖：

- MultiDiGraph 转 DiGraph。
- 平行边按最小 cost 合并。
- OSM node id 与 neuron index 映射。
- Loihi delay 上限编码。
- NavigationResult 路径回映射。
- 不可达目标但 wavefront 仍有局部传播 frame。
- GUI 侧按任意 timestep 重建 wavefront 激活节点、完成边和传播中边。
- GUI 侧有向可达性提示。
- 模拟交通拥堵叠加到动态图。
- 拥堵阻塞当前路线后，wavefront 能重新规划到替代路线。
- 小型 toy graph 跑通导航 planner。

当前验证结果：

```text
13 passed
```

## 常用命令

```bash
conda activate neuro-nav
streamlit run app.py
```

```bash
conda activate neuro-nav
python -m pytest -q
```

```bash
conda activate neuro-nav
python -m compileall -q app.py app_demo.py src tests
```

## 验收标准

1. `streamlit run app.py` 能启动 Web GUI。
2. 输入 `Shinjuku, Tokyo, Japan` 或 bbox 后能加载真实道路网络。
3. 起点/终点经纬度能 snap 到最近道路节点。
4. 点击 `Run SNN Navigation` 后调用 SNN planner。
5. GUI 显示真实地图、道路网络、起点、终点、wavefront、最终路径和小车位置。
6. 全流程不依赖 SUMO。
