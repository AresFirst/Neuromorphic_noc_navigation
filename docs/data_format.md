# 数据格式说明

本文档说明项目中约定的标准图格式、脉冲格式和数据包格式。

## 节点属性

```text
x: float
y: float
region: int
source: str
original_id: str
```

含义：

- `x`、`y`：节点二维坐标
- `region`：节点所属区域编号
- `source`：数据来源，通常为 `most` 或 `most_raw`
- `original_id`：原始数据中的节点 ID

## 边属性

```text
distance: float
base_cost: float
delay_ms: int
original_delay_ms: int
state: str
source: str
original_edge_id: str
```

含义：

- `distance`：几何距离或 lane 平均长度
- `base_cost`：用于最短路径比较的基础代价
- `delay_ms`：最终用于 SNN 波前传播的整数延迟
- `original_delay_ms`：归一化前的延迟记录
- `state`：边状态
- `source`：边属性来源
- `original_edge_id`：原始边 ID

## 边状态

```text
normal
penalized
blocked
```

## Spike trace 格式

```text
neuron_id
spike_time_ms
```

说明：

- 每行表示一个神经元的首次发放时间
- `neuron_id` 为整数节点编号
- `spike_time_ms` 为毫秒单位的时间

## Packet trace 格式

```text
cycle
src_neuron
dst_neuron
src_core
dst_core
packet_type
packet_size
```

说明：

- `cycle`：仿真周期
- `src_neuron` / `dst_neuron`：脉冲前后神经元
- `src_core` / `dst_core`：映射到的 NoC core
- `packet_type`：数据包类型
- `packet_size`：数据包大小

## 图序列化格式

项目导出的 `graph.json` 仍然采用 NetworkX 有向图的通用 JSON 表达，节点和边属性按上述约定保存。
