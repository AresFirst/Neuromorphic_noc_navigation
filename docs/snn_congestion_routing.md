# SNN 拥塞路径规划说明

本文说明当前 Web 演示里的实际逻辑：初始点击“运行 SNN 导航”时不注入任何拥塞；点击“开始”后车辆行驶，途中才随机出现封路型拥塞。每次封路出现后，SNN、Dijkstra、A* 会在同一当前道路状态下串行重规划。

## 初始规划

每次点击“加载杭州地图”后，Web 会在当前杭州 bounding box 内的同一个连通道路分量中随机选择两个不同节点作为起点和终点，并用 `nx.has_path` 保证从起点到终点有可行路径。随后点击“运行 SNN 导航”时，系统按顺序执行：

1. SNN：Brian2Loihi wavefront + STDP parent trace 回溯。
2. Dijkstra：在当前无拥塞图快照上完整规划。
3. A*：在当前无拥塞图快照上完整规划。

初始阶段不会生成 `route_congestion`，也不会关闭任何道路。地图会显示三种算法当前已经得到的路线。

伪代码：

```text
function run_initial_planning(graph, start, goal):
    snn_route = run_brian2loihi_wavefront(graph, start, goal)
    dijkstra_route = run_dijkstra(copy_or_view(graph), start, goal)
    astar_route = run_astar(copy_or_view(graph), start, goal)
    return routes
```

## 行驶中拥塞如何出现

点击“开始”后，车辆按约 30 km/h 行驶。系统根据当前 SNN/可用路线的总长度，把全程最多分成 5 到 10 个拥塞触发点。每次车辆累计行驶到触发距离后，系统从车辆前方约 3 km 范围内随机选一条未来路段作为封路障碍。

当前 Web 配置：

- 最大封路拥塞数：`max_route_congestion_events = 10`。
- 目标封路数：`route_congestion_target_count = 7`。
- 每次封路边数：`route_congestion_edge_count = 1`。
- 预知距离：`route_congestion_lookahead_m = 3000.0`。
- 导航车速：`navigation_speed_mps = 8.33`，约 30 km/h。
- 随机种子：`random_seed = 7`，同一路线下可复现。

封路选择不会封车辆正在行驶的边；优先选择车辆前方较远的未来边，让车辆有机会提前绕行。

伪代码：

```text
function maybe_trigger_route_congestion(vehicle):
    if vehicle.total_distance < next_trigger_distance:
        return no_event

    candidates = future_edges_ahead(vehicle.route, lookahead=3000m)
    candidates = remove_current_edge(candidates)
    candidates = prefer_edges_far_enough_ahead(candidates)
    affected_edge = seeded_random_choice(candidates)

    mark_incident(affected_edge)
    next_trigger_distance += route_length / (target_count + 1)
```

## 封路如何映射到 SNN 和道路图

当前实现把拥塞视为“道路边封闭”，不是“整个路口节点消失”。

被选中的道路边 `u -> v` 会变成硬障碍：

- `edge.state = "blocked"`。
- `edge.snn_synapse_closed = True`。
- `edge.travel_time` 和 `edge.cost` 大幅升高。
- `graph.nodes[v].traffic_node_congestion = 1.0` 仅用于可视化拥塞点。
- 不再设置 `graph.nodes[v].snn_neuron_closed = True`。

这样做的原因是：封一条路不等于关闭整个路口。Dijkstra/A* 和 SNN 都应能从其他未封道路进入同一个路口，从而绕开原封路段。

伪代码：

```text
function apply_closure(edge u->v):
    edge.state = "blocked"
    edge.snn_synapse_closed = true
    edge.travel_time = edge.free_flow_time * 100
    edge.cost = edge.travel_time
    graph.nodes[v].traffic_node_congestion = 1.0
```

车辆移动器也会把 `state="blocked"` 或 `snn_synapse_closed=True` 的边当成硬停止条件；如果没有成功重规划，车辆不会继续穿过封路边。

导航结束或车辆到达终点后，Web 会清理本次行驶中仍处于活跃状态的封路事件，并把道路边状态、下游节点可视化拥塞标记和“拥堵路段”指标恢复为空闲状态。

## 封路后如何重规划

每次封路出现后，系统从车辆当前可重规划节点开始，按顺序运行三种算法：

1. SNN：不使用 CPU wavefront，只调用 Brian2Loihi 从当前节点重新发放 spike，并用 STDP parent trace 回溯新路线。
2. Dijkstra：不读取 SNN spike、parent trace 或旧搜索状态，在当前封路图上完整重算最短路。
3. A*：同样不读取 SNN 状态，在当前封路图上完整重算最短路。

伪代码：

```text
function reroute_after_closure(graph, vehicle, goal):
    source = vehicle.current_edge_end

    snn_route = run_incremental_snn_navigation(
        graph,
        start_node = source,
        goal_node = goal,
        use_loihi = true,
        allow_cpu_fallback = false
    )

    dijkstra_route = run_dijkstra(current_graph_view(graph), source, goal)
    astar_route = run_astar(current_graph_view(graph), source, goal)

    vehicle.route = snn_route if snn_route.success else first_successful_classical_route
    return all_three_routes_for_display
```

在正确的 Brian2Loihi 环境中，车辆优先采用 SNN 路线。若当前 Python 进程没有 Brian2Loihi，SNN 会明确失败且不会降级到 CPU；页面可以用 Dijkstra/A* 的成功路线继续验证车辆和封路流程。

## 耗时口径

- SNN 总规划耗时：当前行驶过程内的累计规划耗时。初始规划包含 Brian2Loihi wavefront、STDP parent trace、路径回溯；拥塞后重规划只累计从当前节点重发 spike 后的 Brian2Loihi wavefront 与回溯耗时。
- Brian2Loihi 仿真器用时：`run_wavefront(use_loihi=True)` 调用耗时。
- CPU wavefront / fallback 用时：严格 SNN 对比中应为空。
- Dijkstra / A* 耗时：每次在当前封路图快照上的完整路径重算耗时。
- 地图 load 用时：只包括加载/构建道路图和缓存道路几何，不包含导航算法耗时。

因此 SNN 单次重规划耗时通常会低于首次规划：首次规划需要完成整张当前图上的完整 Brian2Loihi 波前传播；拥塞后按演示设定只从车辆当前可重规划节点重新发放 spike。表格中的“总规划耗时”会把这些单次耗时累计起来，不会用最近一次重规划覆盖初始耗时。

## 运行环境

Brian2Loihi 安装在 `neuro-nav` 环境中时，需要从该环境启动 Web 服务：

```bash
conda activate neuro-nav
PYTHONPATH=src streamlit run src/gui/app.py
```

如果从 base Python 启动，页面会报告 Brian2Loihi 不可用；这不是算法失败，而是运行解释器没有加载到 `brian2` / `brian2_loihi`。
