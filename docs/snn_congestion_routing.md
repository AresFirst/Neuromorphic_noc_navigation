# SNN 拥塞路径规划说明

本文说明 Web 演示中导航车辆遇到随机拥塞时，SNN 路径规划如何选择新路线，以及拥塞路段如何产生。地图加载逻辑保持不变；下面只描述运行时交通与重规划逻辑。

## 拥塞如何随机出现

模拟交通使用固定场景：没有背景车流随机注入，也没有额外人工可选参数。导航车辆每累计行驶约 `route_congestion_interval_m` 米后，在当前剩余路线的前方随机选择若干条候选边作为拥塞路段。

当前 Web 配置中：

- `route_congestion_interval_m = 5000.0`，即车辆每行驶约 5 km 触发一次路线拥塞检查。
- `route_congestion_edge_count = 2`，每次最多随机选 2 条前方候选边。
- `route_congestion_capacity_multiplier = 0.01`。
- `route_congestion_speed_multiplier = 0.01`。
- 随机数由 `random_seed = 7` 固定，因此同一条路线、同一仿真过程可复现。

候选边选择逻辑：

1. 从车辆当前边的下一条边开始向终点扫描。
2. 优先不关闭车辆正在行驶的边，避免车辆瞬间落在不可通行边上。
3. 默认跳过直接连接终点的最后一条边，尽量让系统有替代路径可选。
4. 对候选边列表执行随机打乱，再取前 `route_congestion_edge_count` 条。

伪代码：

```text
function maybe_trigger_route_congestion(vehicle, current_time):
    if vehicle is None or vehicle.arrived:
        return []

    while vehicle.total_distance >= next_route_congestion_distance:
        candidates = []
        start_index = vehicle.current_edge_index + 1

        for i from start_index to len(vehicle.route) - 2:
            edge = (vehicle.route[i], vehicle.route[i + 1])
            if edge.target == vehicle.destination:
                continue
            if graph.has_edge(edge):
                candidates.append(edge)

        if candidates is empty and vehicle.current_edge exists:
            candidates.append(vehicle.current_edge)

        shuffle(candidates, seeded_rng)
        affected_edges = first N candidates
        next_route_congestion_distance += route_congestion_interval_m

        if affected_edges is not empty:
            incident = TrafficIncident(
                affected_edges = affected_edges,
                start_time = current_time,
                end_time = current_time + route_congestion_duration_seconds,
                capacity_multiplier = 0.01,
                speed_multiplier = 0.01
            )
            incident_generator.incidents.append(incident)
```

## 拥塞如何映射到 SNN

每个仿真步会把活跃拥塞事件应用到道路图边属性。若某条边的容量或速度乘子小于等于 `0.05`，该边会被视为阻塞：

- 道路边 `state = "blocked"`。
- 对应 SNN 突触 `snn_synapse_closed = True`。
- 该边下游节点对应的 SNN 神经元 `snn_neuron_closed = True`。
- 下游节点的拥塞标记 `traffic_node_congestion = 1.0`。

伪代码：

```text
function apply_incident_to_edge(edge u->v, capacity_multiplier, speed_multiplier):
    update travel_time, cost, delay_ms using current speed and capacity

    if capacity_multiplier <= 0.05 or speed_multiplier <= 0.05:
        edge.state = "blocked"
        edge.snn_synapse_closed = true
        graph.nodes[v].snn_neuron_closed = true
        graph.nodes[v].traffic_node_congestion = 1.0
```

## SNN 遇到拥塞时如何选择路线

初始规划使用完整 SNN wavefront：先从起点发放脉冲，得到所有可达节点的首次 spike 时间，再通过 STDP parent trace 从终点回溯到起点，得到 SNN 路径。

拥塞发生后，不重新执行“把整个道路图转换为 SNN”的过程。系统复用已经存在的图/SNN 映射，只从车辆当前所在边的终点节点发放一次新的增量 pulse：

1. 当前车辆节点取 `vehicle.current_edge_end`。
2. 已关闭神经元和突触在增量 wavefront 中不可通行。
3. 为避免不现实的立即折返，若当前边反向边存在，临时把反向边关闭。
4. 增量 wavefront 只在当前图状态上扩散。
5. 根据 spike 时间推断 parent trace。
6. 从终点沿 parent trace 回溯生成候选新路线。
7. 用当前图上的 `travel_time` 计算旧剩余路线 ETA 和新路线 ETA。
8. 只有当新路线 ETA 至少满足改善阈值时，才替换车辆剩余路线；否则保留旧路线并记录未重规划原因。

伪代码：

```text
function reroute_snn_after_congestion(graph, vehicle, destination):
    source = vehicle.current_edge_end
    old_route = vehicle.remaining_route_from_current_edge_end()
    old_eta = eta(graph, old_route)

    planning_graph = graph
    if graph.has_edge(vehicle.current_edge_end, vehicle.current_edge_start):
        planning_graph = graph.copy()
        close reverse edge in planning_graph

    result = run_incremental_snn_navigation(
        planning_graph,
        start_node = source,
        goal_node = destination
    )

    new_route = result.path_nodes
    new_eta = eta(planning_graph, new_route)

    if new_route is empty:
        return keep_old_route(reason = "no_current_route_available")

    if new_route == old_route:
        return keep_old_route(reason = "same_route")

    if old_eta > new_eta * (1 + eta_improvement_threshold):
        vehicle.replace_remaining_route(new_route)
        return use_new_route(reason = "lookahead_congestion or eta_improvement")

    return keep_old_route(reason = "severe_congestion_without_eta_improvement or eta_improvement_too_small")
```

## 与 Dijkstra / A* 的隔离

每次 SNN 规划结果生成后，Dijkstra 和 A* 都会从同一个当前道路图快照上各自完整重算路线：

- Dijkstra 不读取 SNN spike 时间、parent trace 或 SNN 回溯路径。
- A* 不读取 SNN spike 时间、parent trace 或 SNN 回溯路径。
- 两个传统算法也不会共享彼此的搜索状态。
- 传统算法只读取当前图里的边权重、阻塞状态和关闭的 SNN 节点/突触标记，用于判断哪些边或节点不可通行。

伪代码：

```text
function compare_algorithms(graph_snapshot, start, goal):
    snn_result = run_snn_or_incremental_snn(graph_snapshot, start, goal)

    dijkstra_graph = copy(graph_snapshot)
    dijkstra_result = run_dijkstra(dijkstra_graph, start, goal)

    astar_graph = copy(graph_snapshot)
    astar_result = run_astar(astar_graph, start, goal)

    return {
        "snn": snn_result,
        "dijkstra": dijkstra_result,
        "astar": astar_result
    }
```

## Web 指标口径

界面中的耗时指标按实际调用边界记录：

- 地图 load 总用时：当前点击“加载杭州地图”事件中，图数据取回/构建与道路几何缓存的总耗时。若 Streamlit 缓存命中，图数据部分反映缓存取回耗时。
- Brian2Loihi 仿真器用时：`run_wavefront(use_loihi=True)` 的实际调用耗时；如果后端不可用，该指标代表失败检测耗时，随后 CPU fallback 会单独计时。
- CPU wavefront / fallback 用时：CPU reference wavefront 或增量 SNN pulse 的耗时。
- STDP parent trace 用时：`infer_parent_trace_from_spikes` 的耗时。
- 路径重建与成本计算用时：`reconstruct_path_from_parent + compute_path_cost` 的耗时。
- STDP 路径回溯总用时：parent trace、路径重建和成本计算的合计。
- Dijkstra / A* 规划用时：各自在隔离图快照上的完整路径重算耗时。
