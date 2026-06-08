from pathlib import Path
import os

# app_demo.py 是独立演示脚本，不走 src/gui/app.py 的正式模块化闭环。
# 主要用途是快速验证 OSMnx + Brian2 + Folium + Streamlit 环境能否工作。
_MPL_CACHE = Path(__file__).resolve().parent / ".matplotlib-cache"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))
# 清理可能来自其他 conda 环境的 PROJ_LIB，避免 pyproj/OSMnx 读取错误坐标库。
os.environ.pop("PROJ_LIB", None)

import osmnx as ox
import networkx as nx
import folium
import streamlit as st
from streamlit_folium import st_folium
from dataclasses import dataclass
from typing import List
import numpy as np

import brian2 as b2

# demo 使用 Brian2 numpy backend，避免本地临时编译 Cython 带来的安装/权限问题。
b2.prefs.codegen.target = "numpy"

# -------------------------
# 数据类
# -------------------------
@dataclass
class WavefrontFrame:
    # demo 里只记录当前时间点新发放的节点，正式 GUI 会记录累计节点和激活边。
    t: int
    active_nodes: List[int]

@dataclass
class NavigationResult:
    # 最终路径节点序列和用于 wavefront 可视化的帧序列。
    path_nodes: List[int]
    wavefront_frames: List[WavefrontFrame]

# -------------------------
# SNN wavefront + STDP 回溯
# -------------------------
def snn_wavefront(G: nx.DiGraph, start: int, goal: int) -> NavigationResult:
    """
    使用 Brian2 spike wavefront 模拟。

    这里保留 Brian2Loihi 兼容的“图节点 -> 神经元、图边 -> 突触”结构，
    但为了让 demo 稳定运行，使用 Brian2 numpy backend 执行。
    """
    if start not in G:
        raise nx.NodeNotFound(f"start node {start} not found")
    if goal not in G:
        raise nx.NodeNotFound(f"goal node {goal} not found")
    if not nx.has_path(G, start, goal):
        raise nx.NetworkXNoPath(f"no directed path from {start} to {goal}")

    # Brian2 每次运行前清空全局对象，避免 Streamlit rerun 时网络对象叠加。
    b2.start_scope()

    # OSM node id 可能很大且不连续；Brian2 神经元索引必须是 0..N-1 连续整数。
    nodes = list(G.nodes)
    N = len(nodes)
    node_idx_map = {node: i for i, node in enumerate(nodes)}
    idx_node_map = {i: node for node, i in node_idx_map.items()}

    # demo 将路段 length 线性缩放到 1..10 ms，用于生成可见的 spike 传播延迟。
    lengths = [float(data.get("length", 1.0) or 1.0) for _, _, data in G.edges(data=True)]
    min_len = min(lengths) if lengths else 1.0
    max_len = max(lengths) if lengths else 1.0

    for _, _, data in G.edges(data=True):
        length = float(data.get("length", 1.0) or 1.0)
        if max_len > min_len:
            normalized = (length - min_len) / (max_len - min_len)
            delay_ms = 1 + int(round(normalized * 9))
        else:
            delay_ms = 1
        data["delay_ms"] = max(1, delay_ms)

    # 用 NetworkX 最短路作为 demo 的路径输出；正式项目使用 spike parent trace 回溯路径。
    path = nx.shortest_path(G, source=start, target=goal, weight="length")
    path_delay = sum(int(G[u][v].get("delay_ms", 1)) for u, v in zip(path, path[1:]))
    # 限制仿真时长，防止在较大图上 demo 页面长时间阻塞。
    sim_time_ms = max(20, min(500, path_delay + 20))

    # 每个道路节点对应一个 LIF-like 神经元；长不应期保证每个节点最多发放一次。
    G_neurons = b2.NeuronGroup(
        N,
        "v : 1",
        threshold="v > 1.0",
        reset="v = 0",
        refractory=1000 * b2.ms,
        method="exact",
    )
    G_neurons.v = 0

    # 起点由外部 SpikeGeneratorGroup 在 t=0 注入一个脉冲。
    input_group = b2.SpikeGeneratorGroup(
        1,
        indices=np.array([0], dtype=int),
        times=np.array([0.0]) * b2.ms,
    )
    input_synapses = b2.Synapses(input_group, G_neurons, on_pre="v_post += 1.1")
    input_synapses.connect(i=[0], j=[node_idx_map[start]])

    # 图中每条有向边映射为一个带 delay 的突触。
    sources = []
    targets = []
    delays = []
    for u, target_node, data in G.edges(data=True):
        sources.append(node_idx_map[u])
        targets.append(node_idx_map[target_node])
        delays.append(int(data.get("delay_ms", 1)))

    graph_synapses = b2.Synapses(G_neurons, G_neurons, on_pre="v_post += 1.1")
    if sources:
        graph_synapses.connect(i=np.array(sources, dtype=int), j=np.array(targets, dtype=int))
        graph_synapses.delay = np.array(delays, dtype=float) * b2.ms

    # SpikeMonitor 收集每个神经元的发放时间，用于回放 wavefront。
    spike_mon = b2.SpikeMonitor(G_neurons)

    network = b2.Network(input_group, G_neurons, input_synapses, graph_synapses, spike_mon)
    network.run(float(sim_time_ms) * b2.ms, namespace={})

    wavefront_frames = []
    spike_times_ms = np.asarray(spike_mon.t / b2.ms)
    spike_indices = np.asarray(spike_mon.i, dtype=int)
    # demo frame 是按实际发放时间分组的“新激活节点”，不是累计 wavefront。
    times = sorted({int(round(float(t))) for t in spike_times_ms})
    for t in times:
        active_nodes = [
            idx_node_map[int(i)]
            for i, spike_t in zip(spike_indices, spike_times_ms)
            if int(round(float(spike_t))) == t
        ]
        wavefront_frames.append(WavefrontFrame(t=int(t), active_nodes=active_nodes))

    return NavigationResult(path_nodes=path, wavefront_frames=wavefront_frames)

def load_graph(place_name: str, network_type: str):
    # 直接调用 OSMnx 下载真实道路图；正式项目还会做 GraphML 缓存和 fallback。
    G = ox.graph_from_place(place_name, network_type=network_type, simplify=True)
    try:
        # travel_time 不是 demo 必需字段，但添加后便于后续扩展比较。
        G = ox.add_edge_speeds(G)
        G = ox.add_edge_travel_times(G)
    except Exception:
        pass
    return G

def main():
    st.set_page_config(page_title="Neuromorphic Navigation Brian2Loihi", layout="wide")
    st.title("Neuromorphic Navigation Demo - Brian2Loihi")

    # demo 使用地名加载，不提供 bbox、交通模拟和正式 NavigationResult 调试区。
    place = st.text_input("Place name", "Shinjuku, Tokyo, Japan")
    network_type = st.selectbox("Network type", ["drive", "walk", "bike"], index=0)
    cached_load_graph = st.cache_resource(load_graph)

    if st.button("Load map"):
        # Streamlit cache_resource 缓存 OSMnx 下载结果，避免每次控件变化重新请求网络。
        st.session_state["G"] = cached_load_graph(place, network_type)
        st.session_state.pop("nav_result", None)

    if "G" not in st.session_state:
        return

    G = st.session_state["G"]
    st.write(f"Nodes: {len(G.nodes)}, Edges: {len(G.edges)}")

    # demo 用节点列表 index 选起终点；正式 GUI 使用经纬度输入并 snap 到最近道路节点。
    node_list = list(G.nodes)
    source_idx = st.slider("Start node index", 0, len(node_list)-1, 0)
    target_idx = st.slider("Goal node index", 0, len(node_list)-1, min(200, len(node_list)-1))

    source = node_list[source_idx]
    target = node_list[target_idx]

    G_digraph = nx.DiGraph()
    # OSMnx MultiDiGraph 中可能存在平行边；demo 转成 DiGraph 时只保留最短 length 边。
    for node, data in G.nodes(data=True):
        G_digraph.add_node(node, x=data["x"], y=data["y"])
    for u, v, data in G.edges(data=True):
        length = float(data.get("length", 1.0) or 1.0)
        if not G_digraph.has_edge(u, v) or length < float(G_digraph[u][v].get("length", float("inf"))):
            G_digraph.add_edge(u, v, length=length)

    if st.button("Run SNN navigation"):
        try:
            # 运行 demo wavefront，并将结果保存到 session_state 以便地图 slider rerun 后仍可显示。
            st.session_state["nav_result"] = snn_wavefront(G_digraph, source, target)
            st.session_state["source"] = source
            st.session_state["target"] = target
        except Exception as exc:
            st.session_state.pop("nav_result", None)
            st.error(str(exc))

    if "nav_result" not in st.session_state:
        return

    nav_result = st.session_state["nav_result"]
    path = nav_result.path_nodes
    wavefront_frames = nav_result.wavefront_frames

    coords = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in path]
    center = coords[0]
    # Folium 使用 (lat, lon)，OSMnx 节点属性是 x=lon, y=lat。
    m = folium.Map(location=center, zoom_start=16)

    # 道路绘制数量会显著影响前端性能，因此提供 slider 做截断。
    max_edges_to_draw = st.slider("Road edges to draw", 200, min(8000, len(G_digraph.edges)), 2000, 100)
    for idx, (u, v) in enumerate(G_digraph.edges()):
        if idx >= max_edges_to_draw:
            break
        folium.PolyLine(
            [(G.nodes[u]["y"], G.nodes[u]["x"]), (G.nodes[v]["y"], G.nodes[v]["x"])],
            color="gray",
            weight=2,
            opacity=0.25,
        ).add_to(m)

    folium.Marker(coords[0], popup="Start", icon=folium.Icon(color="green")).add_to(m)
    folium.Marker(coords[-1], popup="Goal", icon=folium.Icon(color="red")).add_to(m)

    if wavefront_frames:
        if len(wavefront_frames) > 1:
            frame_idx = st.slider("Wavefront frame", 0, len(wavefront_frames) - 1, len(wavefront_frames) - 1)
        else:
            frame_idx = 0
        # 橙色点表示当前 frame 内发放的神经元/道路节点。
        for n in wavefront_frames[frame_idx].active_nodes:
            folium.CircleMarker(
                location=(G.nodes[n]["y"], G.nodes[n]["x"]),
                radius=3,
                color="orange",
                fill=True,
            ).add_to(m)

    folium.PolyLine(coords, color="blue", weight=6, opacity=0.9).add_to(m)

    car_pos = 0
    if len(coords) > 1:
        # demo 中的小车不是自动动画，而是通过 slider 指定路径上的当前位置。
        car_pos = st.slider("Car position along path", 0, len(coords) - 1, 0)
    folium.Marker(
        coords[car_pos],
        popup="Car",
        icon=folium.Icon(color="blue", icon="car", prefix="fa"),
    ).add_to(m)

    st_folium(m, width=1200, height=700)


if __name__ == "__main__":
    main()
