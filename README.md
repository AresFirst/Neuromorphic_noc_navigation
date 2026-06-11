# Neuromorphic OSM SNN Navigation

这是一个“真实道路地图 + SNN 路径规划 + Web GUI 可视化”的精简项目。

当前主线不再使用 SUMO，也不再依赖 MoST 数据集。地图来自 OpenStreetMap，使用 OSMnx 下载和缓存；计算层临时转换成 `networkx.DiGraph`；规划层使用 Brian2Loihi wavefront 或 CPU-compatible wavefront；最终结果在 Streamlit Web 页面中显示。GUI 默认保留 OpenStreetMap 标准底图样式；如果准备本地 MapLibre 矢量瓦片或本地 OSM 栅格瓦片，也可以离线渲染。

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
    -> Streamlit + OpenStreetMap/MapLibre/Canvas GUI
       - 本地矢量瓦片或本地道路几何
       - 道路网络
       - 起点/终点
       - wavefront 激活节点和边
       - 最终路径
       - 小车位置
```

`networkx.DiGraph` 只作为计算层使用，不作为最终地图显示格式。GUI 中的道路显示始终基于 OSM 道路几何；默认底图使用 OpenStreetMap 标准栅格样式，如果提供本地 `hangzhou.mbtiles` 或 `hangzhou.pmtiles`，底图也可以由 MapLibre 使用本地矢量瓦片渲染。

## 项目结构

```text
.
├── app.py                         # Streamlit 入口
├── desktop_app.py                 # PySide6 桌面入口
├── app_demo.py                    # 独立 demo，便于快速试验
├── configs/
│   └── brian2loihi.yaml           # SNN 参数
├── loihi_planner/                 # Brian2Loihi wavefront 与路径回溯
├── src/
│   ├── gui/
│   │   ├── app.py                 # Web GUI 主实现
│   │   ├── desktop_viewer.py      # PySide6 桌面地图/车辆/路线可视化
│   │   └── offline_map.py         # OSM/MapLibre/Canvas 地图渲染
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

- `desktop_app.py`

  PySide6 桌面 GUI 的根入口。用户运行：

  ```bash
  python desktop_app.py
  ```

  时，实际会进入 `src/gui/desktop_viewer.py` 中的 `main()`。桌面端不依赖浏览器，只显示杭州地图、DiGraph/SNN 节点、SNN 路线和自动行驶车辆。

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
  - 固定加载浙江省杭州市地图。
  - 起点和终点经纬度输入。
  - 起终点 snap 到最近 OSM 道路节点。
  - 调用 `run_navigation()` 执行 SNN wavefront。
  - 调用离线地图组件绘制普通道路、最终路径、wavefront、交通拥堵、小车 marker。
  - wavefront timestep slider。
  - 车辆 `开始 / 暂停 / 结束` 自动行驶控制。
  - 模拟交通动态推进和当前状态下的重规划。
  - 页面底部指标和 JSON 调试信息。

  这个文件是用户实际交互最多的地方，也是把地图、SNN、交通和可视化串起来的闭环入口。

- `src/gui/desktop_viewer.py`

  PySide6 桌面地图窗口。它复用现有杭州 OSM 缓存、`osmnx_multidigraph_to_digraph()`、
  `run_navigation()` 和 `path_nodes_to_latlon()`，不改 SNN 或交通核心结构。当前桌面端提供：

  - 本地窗口地图，不经过 Streamlit 或浏览器。
  - 可选本地 `data/tiles/osm/{z}/{x}/{y}.png` OSM 栅格瓦片。
  - 没有本地瓦片时，直接绘制 OSM 道路 geometry。
  - DiGraph 节点点层，双击节点显示 DiGraph node、SNN neuron index 和 OSM node id。
  - 起终点经纬度输入、最近道路节点吸附、SNN 导航。
  - 红色路线和车辆 `开始 / 暂停 / 结束` 自动播放。

- `src/gui/offline_map.py`

  地图渲染层。它不参与路径计算，只负责把当前 GUI 状态转换为前端 GeoJSON payload，并渲染：

  - OpenStreetMap 标准栅格底图。
  - 本地 `data/tiles/osm/{z}/{x}/{y}.png` 栅格瓦片。
  - 可选本地 Leaflet 前端资源。
  - 本地 MapLibre GL JS。
  - 本地 `data/tiles/hangzhou.mbtiles` 矢量瓦片。
  - 或本地 `data/tiles/hangzhou.pmtiles`，需要同时提供 `pmtiles.js`。
  - 严格离线且缺少本地 OSM/MapLibre 资源时，才使用 Canvas 降级渲染本地 GraphML 道路、路径、车辆、拥堵和 wavefront。

### 地图层

- `src/maps/osmnx_loader.py`

  负责真实道路地图加载。GUI 主线固定使用浙江省杭州市，优先读取稳定缓存文件：

  - `data/osm_cache/hangzhou_drive.graphml`
  - 或其他 network type 对应的 `hangzhou_{network_type}.graphml`

  它的主要职责是：

  - 调用 OSMnx 从 OpenStreetMap 下载道路网络。
  - 给道路边添加 speed 和 travel time。
  - 下载后保存为 GraphML 缓存。
  - 下次加载杭州区域时优先读取本地缓存。
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
  - 保留道路 `geometry`，用于 GUI 离线渲染真实道路形状。
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

  `TrafficSnapshot` 描述当前 traffic step 中哪些边拥堵、哪些边阻塞、哪些节点受到抑制。新的动态仿真引擎会把当前 edge attributes 转成这个结构供 GUI overlay 使用。

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
conda install -c conda-forge osmnx geopandas shapely pyproj folium streamlit streamlit-folium pyside6 pytest
pip install -e .
```

## 启动 Web GUI

```bash
conda activate neuro-nav
streamlit run app.py
```

打开页面后的推荐流程：

1. 选择 `道路网络类型`，默认 `drive` 会保留真实机动车道路方向。
2. 点击 `加载杭州地图`，系统优先读取 `data/osm_cache/hangzhou_drive.graphml`。
3. 输入 `起点纬度 / 起点经度` 和 `终点纬度 / 终点经度`，坐标必须位于杭州固定范围内。
4. 点击 `运行 SNN 导航`。
5. 查看 wavefront、最终路径、指标和车辆位置。
6. 点击 `开始` 后车辆会自动沿当前路线行驶；`暂停` 会保留车辆和交通状态；`结束` 会停止本次导航。
7. 如果要模拟动态拥堵，打开 `启用模拟交通`，暂停时可调整交通参数并点击 `应用当前交通设置`，恢复开始时会基于当前拥堵状态重新评估路线。

## 启动桌面 GUI

```bash
conda activate neuro-nav
python desktop_app.py
```

桌面端适合只观察地图、节点、路线和车辆，不走 Web 页面。推荐流程：

1. 点击 `加载杭州地图`，系统优先读取 `data/osm_cache/hangzhou_drive.graphml`。
2. 根据需要调整 `起点纬度 / 起点经度` 和 `终点纬度 / 终点经度`。
3. 点击 `运行 SNN 导航`，红色路线会显示在地图上。
4. 点击 `开始`，红色车辆点会沿路线自动移动；`暂停` 会保留当前位置；`结束` 会重置本次播放。
5. 双击地图上的蓝色节点，可查看该点对应的 DiGraph node、SNN neuron index 和原始 OSM node id。

如果存在 `data/tiles/osm/{z}/{x}/{y}.png` 本地瓦片，桌面端会直接读取本地瓦片作为底图；没有本地瓦片时，会绘制 OSM 道路 geometry、节点、路线和车辆。

## OpenStreetMap 样式与离线瓦片

Web GUI 默认使用 OpenStreetMap 标准栅格底图，以保留原版 OSM 的地图样式。这个默认模式需要浏览器能访问在线 OSM 瓦片和 Leaflet 前端资源。

如果要完全断网但仍保留接近原版 OpenStreetMap 的视觉样式，请准备本地栅格瓦片和 Leaflet 资源：

```text
data/offline_map/assets/leaflet.js
data/offline_map/assets/leaflet.css
data/tiles/osm/{z}/{x}/{y}.png
```

本地栅格瓦片目录使用标准 XYZ 结构。GUI 检测到 `data/tiles/osm` 中存在 `.png`、`.jpg`、`.jpeg` 或 `.webp` 瓦片后，会通过本地 HTTP 服务读取这些瓦片；如果缺少本地 Leaflet 资源，则 Leaflet 仍会从 CDN 加载。

桌面 GUI 不需要 Leaflet；它会用 Qt 直接读取同一个 `data/tiles/osm` 目录。

要启用高性能本地 MapLibre 矢量瓦片，请准备：

```text
data/offline_map/assets/maplibre-gl.js
data/offline_map/assets/maplibre-gl.css
data/tiles/hangzhou.mbtiles
```

可选 PMTiles 模式：

```text
data/offline_map/assets/pmtiles.js
data/tiles/hangzhou.pmtiles
```

这些大文件默认被 `.gitignore` 忽略。GUI 会自动检测资源：

- 检测到 `hangzhou.mbtiles`：使用本地 MBTiles 矢量瓦片。
- 检测到 `hangzhou.pmtiles` 且有 `pmtiles.js`：使用本地 PMTiles。
- 检测到 `data/tiles/osm`：使用本地 OpenStreetMap 栅格瓦片。
- 没有本地瓦片：默认使用在线 OpenStreetMap 标准底图。
- 严格离线且没有 OSM/MapLibre 本地资源：使用 Canvas 离线降级渲染。

建议将杭州矢量瓦片限制在项目固定范围附近，避免文件过大：

```text
北 30.420
南 30.080
东 120.360
西 119.950
```

## Web 页面坐标说明

### 固定杭州范围

Web GUI 不再暴露 place name 或手动 bbox 输入。地图区域固定为浙江省杭州市，当前代码中的范围为：

```text
North = 30.420
South = 30.080
East  = 120.360
West  = 119.950
```

起点和终点坐标会先做杭州范围校验，再 snap 到最近道路节点。

### Start / Goal Coordinates

页面里的：

- `起点纬度`
- `起点经度`
- `终点纬度`
- `终点经度`

不是直接作为 SNN 节点使用。系统会先把这些经纬度 snap 到最近的 OSM 道路节点，然后使用 snap 后的节点 ID 作为：

- 起点 node id
- 终点 node id
- 起点 neuron index
- 终点 neuron index

因此，如果你输入的坐标在道路旁边，实际起终点会落到最近道路节点。页面下方会显示 snapped 后的 `起点节点` 和 `终点节点`。

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

当点击 `运行 SNN 导航` 后，起点 neuron 注入初始 spike。脉冲沿道路边传播，经过突触延迟后激活下一个 neuron。

GUI 中：

- 青色点：当前 timestep 之前已经发放过 spike 的 neuron。
- 青色线：当前 timestep 之前已经传播完成的 edge/synapse。
- 橙色虚线：当前 timestep 正在传播中的 edge/synapse，即前驱 neuron 已发放，但延迟还没有结束。
- `波前时间步（毫秒）`：按毫秒拖动的 wavefront 时间滑块，用于观察神经元逐步激活过程。
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

### 起点 / 终点 / 车辆

- 绿色点：snap 后的起点节点。
- 紫色点：snap 后的终点节点。
- 红色点：主导航车辆位置。
- 点击 `开始` 后，车辆会沿当前路线自动行驶。
- 点击 `暂停` 后，车辆位置、当前路线、交通状态和仿真时间都会保留。
- 暂停后调整交通参数，再点击 `开始`，系统会基于当前 edge 状态重新评估路线。
- 点击 `结束` 后，当前导航仿真停止。

车辆位置来自 `Vehicle.position_on_edge` 和当前 edge geometry 插值，不再使用手动 `Car position` slider。

## 模拟交通拥堵与动态重规划

本项目不接入真实交通 API。Web GUI 中的 `启用模拟交通` 是一个轻量级“路段级动态拥塞模拟器”，用于验证：

```text
背景车辆运行时生成
    -> 当前路段车辆数上升
    -> BPR travel_time / current_speed 更新
    -> 当前路线 ETA 变差
    -> 导航车辆只基于当前 edge 状态重规划
```

重要约束：拥塞不是出发前预先写死的。`DynamicRouter` 不能访问未来事件、未来车辆位置或未来拥塞状态；它只能读取当前 graph edge attributes，例如 `travel_time/current_speed/congestion_level`。

操作流程：

1. 先加载杭州地图。
2. 输入起点和终点。
3. 在侧边栏打开 `启用模拟交通`。
4. 选择 `交通模式`，例如 `高峰` 或 `事故/施工`。
5. 点击 `运行 SNN 导航`，系统会启动 `SimulationEngine` 并创建主导航车辆。
6. 点击 `开始`，页面每次刷新会推进一个或多个 timestep。
7. 每个 timestep 会生成背景车辆、触发当前事件、移动车辆、更新 edge 状态并检查是否重规划。
8. 如果当前观测状态显示新路线 ETA 明显更好，红色路径会变化；旧路线会以橙色虚线显示。

交通参数含义：

- `交通模式`：背景车辆模式。`普通` 为普通流量，`高峰` 为高峰波动，`事故/施工` 会启用运行时事件。
- `背景车辆生成率（辆/分钟）`：数值越大，路段车辆数和拥塞越容易上升。
- `交通时间步（秒）`：每次仿真步长 `dt`。
- `每次刷新推进步数`：自动行驶时每次页面刷新推进多少个 timestep。
- `事故/施工概率（每分钟）`：每分钟触发事故/施工的概率，仅 `事故/施工` 模式下使用。
- `重规划检查间隔（秒）`：主导航车辆多久检查一次是否需要重规划。
- `最小重规划间隔（秒）`：两次重规划之间的最小间隔，避免路线频繁抖动。
- `重规划拥堵阈值`：前方路段拥塞超过该值时，会进入重规划候选。
- `交通随机种子`：相同 seed 下，车辆生成和事件触发可复现。
- `交通路段绘制数量上限`：最多绘制多少条交通状态边，用于控制性能。

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
    -> 当前时刻的 SNN wavefront 或 dynamic shortest path
```

地图颜色：

- 绿色线：`congestion_level` 0.0 ~ 0.4。
- 黄色线：`congestion_level` 0.4 ~ 0.7。
- 红色线：`congestion_level` 0.7 ~ 0.9。
- 深红线：`congestion_level` 0.9 ~ 1.0。
- 橙色虚线：发生重规划后，上一条剩余路线。

页面指标：

- `仿真时间`：当前仿真时间。
- `车辆数`：当前仍在路网中的车辆数量，包括背景车辆和主导航车辆。
- `平均速度`：全网平均当前速度。
- `拥堵路段`：当前拥塞路段数量。
- `重规划次数`：主导航车辆重规划次数。

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

Streamlit 的交互模型是：每次控件变化都会重新运行页面脚本。旧版 Folium/Leaflet 需要在每次 rerun 时创建大量前端对象，因此杭州级别的道路图会明显卡顿。当前 GUI 使用轻量 HTML 组件渲染 OpenStreetMap/MapLibre/Canvas，主流程不再使用 `st_folium`。

本项目已做的优化：

- 地图道路几何在加载 OSM 图后预计算，并保存在 `st.session_state` 中。
- 前端默认使用 OpenStreetMap 标准栅格底图，并一次性叠加当前 GeoJSON payload。
- 如果提供 `data/tiles/osm/{z}/{x}/{y}.png`，浏览器从本地读取 OSM 栅格瓦片。
- 如果提供 `data/tiles/hangzhou.mbtiles`，基础底图由 MapLibre 使用本地矢量瓦片渲染，通常比逐条绘制道路更流畅。
- 侧边栏提供 `显示基础道路网络`，可以临时关闭本地 GraphML 道路叠加，只显示路径、wavefront 和车辆。
- 侧边栏提供 `道路绘制数量上限`，限制本地 GraphML 道路叠加数量。
- 侧边栏提供 `波前节点绘制数量上限`，限制激活 neuron 点数量。
- 侧边栏提供 `交通路段绘制数量上限`，限制拥堵边绘制数量。

推荐设置：

```text
道路绘制数量上限       = 800 到 1500
波前节点绘制数量上限   = 300 到 800
显示基础道路网络       = 关闭后自动行驶刷新最快
OSM 栅格瓦片           = 要保留原版 OSM 样式时推荐提供 data/tiles/osm
本地矢量瓦片           = 要更高性能时推荐提供 hangzhou.mbtiles
```

如果只是观察车辆沿路径移动，可以关闭 `显示基础道路网络`。如果只是观察 SNN 扩散，可以降低 `道路绘制数量上限`，保留 wavefront 点和边。

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
- `wavefront_time_max_ms`：GUI 中 `波前时间步（毫秒）` 的最大时间。
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
- 路段级动态字段初始化。
- 运行时 incident 只在 timestep 推进时激活。
- DynamicRouter 只根据当前 travel_time 和 congestion_level 重规划。
- SimulationEngine 运行时生成车辆并更新指标。
- 小型 toy graph 跑通导航 planner。

当前验证结果以本地运行的 `python -m pytest -q` 为准。

## 常用命令

```bash
conda activate neuro-nav
streamlit run app.py
```

```bash
conda activate neuro-nav
python desktop_app.py
```

```bash
conda activate neuro-nav
python -m pytest -q
```

```bash
conda activate neuro-nav
python -m compileall -q app.py app_demo.py desktop_app.py src tests
```

## 验收标准

1. `streamlit run app.py` 能启动 Web GUI。
2. `python desktop_app.py` 能启动 PySide6 桌面 GUI。
3. 页面固定地图区域为浙江省杭州市，且不暴露 place/bbox 输入。
4. 起点/终点经纬度能限制在杭州范围内，并 snap 到最近道路节点。
5. 点击 `运行 SNN 导航` 后调用 SNN planner。
6. Web GUI 默认使用 OpenStreetMap 标准底图，并可切换到本地 OSM 栅格瓦片、MapLibre 矢量瓦片或 Canvas 降级渲染。
7. 桌面 GUI 能显示本地 OSM 瓦片或 OSM 道路 geometry、DiGraph/SNN 节点、路线和车辆。
8. 全流程不依赖 SUMO。
9. 打开 `启用模拟交通` 后，背景车辆会随 timestep 持续生成。
10. 路段颜色会根据当前 `congestion_level` 动态变化。
11. 导航车辆只基于当前 `travel_time/current_speed/congestion_level` 判断是否重规划。
12. 若发生重规划，JSON 日志会显示旧 ETA、新 ETA、重规划时间和受影响 edge。
