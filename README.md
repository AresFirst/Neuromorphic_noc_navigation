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
│   │   ├── edge_state.py          # 路段动态交通字段初始化
│   │   ├── flow_generator.py      # 运行时背景车辆需求生成
│   │   ├── incident_generator.py  # 运行时事故/施工事件
│   │   ├── dynamic_router.py      # 当前状态下的动态重规划
│   │   ├── simulation_engine.py   # 动态交通主循环
│   │   ├── traffic_state_updater.py
│   │   ├── vehicle.py
│   │   ├── vehicle_simulator.py
│   │   ├── metrics.py
│   │   ├── simulator.py           # 旧热点式接口，保留兼容
│   │   └── state.py               # TrafficSnapshot 数据结构
│   └── nmn/loihi/                 # 兼容导出
└── tests/
    ├── test_dynamic_traffic_sim.py
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

  - 固定杭州核心 bbox 的 OSM 地图加载按钮。
  - 起点和终点经纬度输入。
  - 起终点 snap 到最近 OSM 道路节点。
  - 调用 `run_navigation()` 执行 SNN wavefront。
  - Folium 地图绘制。
  - SNN / Dijkstra / A* 路线、交通拥堵、小车 marker 的 overlay。
  - 自动行驶、距离触发拥塞和增量 SNN 重规划。
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

  定义 GUI 兼容的交通快照状态：

  - `TrafficEdgeState`
  - `TrafficSnapshot`

  `TrafficSnapshot` 描述当前 traffic step 中哪些边拥堵、哪些边阻塞、哪些节点受到抑制。新的动态仿真引擎会把当前 edge attributes 转成这个结构供 Folium overlay 使用。

- `src/traffic/simulator.py`

  旧版热点式拥堵接口，保留是为了兼容历史测试和外部脚本。当前 GUI 主线已经切到 `SimulationEngine`，不会再用它预先挑选热点道路。

- `src/traffic/edge_state.py`

  为每条 OSM edge 补齐动态交通字段：

  - `free_flow_speed`
  - `current_speed`
  - `free_flow_time`
  - `travel_time`
  - `capacity`
  - `vehicle_count`
  - `density`
  - `flow`
  - `congestion_level`
  - `last_updated_time`
  - `delay_ms`

  如果 OSM 缺少 `maxspeed` 或 `lanes`，会根据 `highway` 类型设置默认速度和容量。

- `src/traffic/flow_generator.py`

  运行时背景车辆生成器。每个 timestep 根据当前时间生成新的 OD 需求，支持 `normal`、`peak`、`incident` 模式。它不会提前生成整段仿真的拥堵结果。

- `src/traffic/incident_generator.py`

  运行时突发事件生成器。事故和施工只会在仿真推进到某个 timestep 时按概率触发。事件触发后才影响 edge capacity / speed，`DynamicRouter` 不会读取未来事件。

- `src/traffic/traffic_state_updater.py`

  根据当前车辆分布和当前活跃事件，用 BPR 函数更新每条 edge 的 `travel_time/current_speed/congestion_level`。

- `src/traffic/vehicle.py`

  定义背景车辆和主导航车辆的状态，包括 route、当前 edge、edge 上的位置、是否允许重规划、是否已到达。

- `src/traffic/vehicle_simulator.py`

  按当前 edge `current_speed` 推动车辆移动。车辆到达 edge 末端后进入下一条 edge；到达 destination 后从仿真中移除。

- `src/traffic/dynamic_router.py`

  主导航车辆的在线重规划器。它只读取当前 graph edge attributes，例如 `travel_time/current_speed/congestion_level`，不会访问未来事件、未来流量或未来车辆位置。

- `src/traffic/simulation_engine.py`

  动态交通主循环。每个 timestep 按如下顺序执行：

  ```text
  FlowGenerator 生成当前背景车辆
      -> IncidentGenerator 触发/结束当前事件
      -> VehicleSimulator 移动车辆
      -> TrafficStateUpdater 更新 edge 状态
      -> DynamicRouter 基于当前状态决定是否重规划
      -> GUI 读取当前 graph 进行可视化
  ```

- `src/traffic/metrics.py`

  记录动态仿真指标和 baseline 对比，包括静态最短路、动态最短路和项目 SNN 路由结果。

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

1. 点击 `加载杭州地图`，加载固定的西湖区 / 拱墅区 / 余杭区 / 上城区附近 bbox。
2. 页面固定使用机动车道路，并在项目图中补齐反向边；Web 端不再暴露道路网络类型选项。
3. 输入 `起点纬度 / 起点经度` 和 `终点纬度 / 终点经度`。
4. 系统会把起点和终点 snap 到最近 OSM 道路节点。
5. 点击 `运行 SNN 导航`，初始路线默认使用 Brian2Loihi 后端；后端不可用时自动降级。
6. 点击 `开始` 后车辆自动行驶。车辆每行驶约 5 km，前方路线会随机出现局部拥塞。
7. 查看地图底图、完整路线、拥塞路段、小车位置和 SNN / Dijkstra / A* 耗时对比。

## Web 页面坐标说明

### 固定 Bounding Box

Web GUI 使用固定矩形地图裁剪框，不再暴露地名或 bbox 输入。当前范围约为旧杭州固定 bbox 的 1/4：

- `North`：北边界，最大纬度 latitude。
- `South`：南边界，最小纬度 latitude。
- `East`：东边界，最大经度 longitude。
- `West`：西边界，最小经度 longitude。

```text
North = 30.3900
South = 30.2200
East  = 120.2350
West  = 120.0300
```

该范围覆盖西湖区、拱墅区、余杭区、上城区附近的演示区域。

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
- 小车位置来自 `Vehicle.position_on_edge`，自动行驶时随当前 edge 前进。

当前版本通过 `开始 / 暂停 / 结束` 控制自动行驶。页面自动推进 timestep，并在达到距离阈值时触发前方拥塞和重规划。

## 模拟交通拥堵与动态重规划

本项目不接入真实交通 API。Web GUI 使用固定的路段级动态拥塞场景，用于验证：

```text
导航车辆累计行驶距离达到阈值
    -> 前方路线随机局部拥塞
    -> 对应 synapse / 下游 neuron 关闭
    -> SNN 从当前节点增量发放脉冲
    -> Dijkstra / A* 使用当前图快照完整重算
```

重要约束：拥塞不是出发前预先写死的。`DynamicRouter` 不能访问未来事件、未来车辆位置或未来拥塞状态；它只能读取当前 graph edge attributes，例如 `travel_time/current_speed/congestion_level/state/snn_synapse_closed`。

操作流程：

1. 先加载 OSM 地图。
2. 输入起点和终点。
3. 点击 `运行 SNN 导航`。
4. 点击 `开始`，系统会启动 `SimulationEngine` 并创建主导航车辆。
5. 页面自动推进 timestep；车辆每行驶约 5 km 会触发前方局部拥塞。
6. 如果当前观测状态显示新路线 ETA 明显更好，红色路径会变化；旧路线会以橙色虚线显示。

当前 Web GUI 不再暴露动态交通参数。固定演示场景为：

- 无背景车辆噪声。
- 车辆每行驶约 5 km 触发一次前方局部随机拥塞。
- 拥塞路段对应的突触标记为关闭，下游节点对应神经元标记为关闭。
- SNN 重规划复用已构建图/SNN 映射，从当前车辆节点重新发放脉冲。
- Dijkstra 和 A* 每次使用隔离图快照完整重新计算路线。

每条 edge 维护的动态字段包括：

- `length`
- `free_flow_speed`
- `current_speed`
- `free_flow_time`
- `travel_time`
- `capacity`
- `vehicle_count`
- `density`
- `flow`
- `congestion_level`
- `last_updated_time`

动态交通如何影响 SNN/路由：

```text
当前 edge 上车辆数 vehicle_count
    -> density / flow / volume-capacity ratio
    -> BPR travel_time
    -> current_speed
    -> congestion_level
    -> cost / delay_ms
    -> blocked edge / closed neuron / closed synapse
    -> 当前时刻的增量 SNN pulse 或 Dijkstra/A* 完整重算
```

地图颜色：

- 绿色线：`congestion_level` 0.0 ~ 0.4。
- 黄色线：`congestion_level` 0.4 ~ 0.7。
- 红色线：`congestion_level` 0.7 ~ 0.9。
- 深红线：`congestion_level` 0.9 ~ 1.0。
- 橙色虚线：发生重规划后，上一条剩余路线。
- 红色粗线：SNN 当前路线。
- 蓝色虚线：Dijkstra 路线；仅当它与 SNN 路线不同时绘制。
- 绿色虚线：A* 路线；仅当它与 SNN/Dijkstra 路线不同时绘制。

页面指标：

- `Sim time`：当前仿真时间。
- `Vehicles`：当前仍在路网中的车辆数量，包括背景车辆和主导航车辆。
- `Avg speed`：全网平均当前速度。
- `Congested edges`：当前拥塞路段数量。
- `Reroutes`：主导航车辆重规划次数。

导航结果下方会显示算法运行耗时对比表：

- `SNN`：项目当前的 spike wavefront 路由耗时。
- `Dijkstra`：独立运行 NetworkX Dijkstra，不读取 SNN spike 或 parent trace。
- `A*`：独立运行 NetworkX A*；OSM 图使用基于直线距离的保守启发式，普通 toy graph 退回零启发式以保持最优性。
- 动态拥塞后的 SNN 行表示增量 pulse 耗时；Dijkstra/A* 行表示隔离图快照上的完整重算耗时。
- `累计耗时` 统计动态拥塞后的重规划耗时，不把初始 Brian2Loihi 建网成本混入。

日志和 JSON 调试区会显示：

- `navigation_vehicle_travel_time`
- `number_of_reroutes`
- `total_distance`
- `average_network_speed`
- `average_congestion_level`
- `number_of_congested_edges`
- `old_route_eta_before_reroute`
- `new_route_eta_after_reroute`
- `reroute_time`
- `affected_edge_ids`

注意：`SimulationEngine` 会持有一份从 `base_graph` copy 出来的动态图。背景车辆、事故和路段状态只存在于这个动态图中，不会污染原始 OSM 图。

## Web 性能与卡顿处理

Streamlit 的交互模型是：每次控件变化都会重新运行页面脚本。Folium 地图也是重新生成一个 HTML/Leaflet 地图。因此，当道路边很多、激活点很多时，浏览器端会卡顿。

本项目已做的优化：

- 地图道路几何在加载 OSM 图后预计算，并保存在 `st.session_state` 中。
- Folium 使用 `prefer_canvas=True`，大量线段会尽量走 canvas 渲染。
- `st_folium(..., returned_objects=[])`，减少前端返回对象带来的开销。
- Web 端不再额外绘制基础道路网络，只使用地图底图、完整路线、拥塞路段和 marker。
- Web 端不再绘制 wavefront 节点和传播边。
- 地图缩放、拖动、滚轮缩放、双击缩放等交互已关闭，减少瓦片请求和前端重绘。
- 交通拥塞路段最多绘制 80 条。

## 双向道路与不可达问题

Web GUI 固定使用机动车道路，并在项目 `DiGraph` 中为每条道路补齐反向边。因此当前演示不保留 OSM 单行道限制。

如果仍然不可达，通常是因为：

- 起点和终点位于不同连通分量。
- 拥塞事件关闭了关键神经元/突触。
- 坐标 snap 到了封闭小路、高架匝道或边界附近孤立道路。

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
- `algorithm_benchmarks`：Dijkstra、A* 等传统路径算法的独立运行耗时和路径摘要。
- `benchmark_cost_attr`：传统路径算法对比时使用的边权重属性，默认是 `cost`。

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
- 路段级动态字段初始化。
- 运行时 incident 只在 timestep 推进时激活。
- DynamicRouter 只根据当前 travel_time 和 congestion_level 重规划。
- SimulationEngine 运行时生成车辆并更新指标。
- 小型 toy graph 跑通导航 planner。

当前验证结果：

```text
17 passed
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
2. 点击 `加载杭州地图` 后能加载固定杭州核心 bbox 的真实机动车道路网络。
3. 起点/终点经纬度能 snap 到最近道路节点。
4. 点击 `运行 SNN 导航` 后调用 SNN planner。
5. GUI 显示真实地图、起点、终点、完整路线、拥塞路段和小车位置，不绘制 wavefront 节点。
6. 全流程不依赖 SUMO。
7. 自动行驶后，车辆每行驶约 5 km 会触发前方局部拥塞。
8. 拥塞会关闭对应突触和下游神经元，并在地图上高亮拥塞路段。
9. SNN 重规划复用已构建图/SNN 映射，从当前车辆节点增量发放脉冲。
10. Dijkstra 和 A* 每次使用隔离图快照完整重算；若路线与 SNN 不同，会用不同颜色绘制。
