# 项目结构说明

本文档说明 `neuromorphic_noc_navigation` 当前和建议中的目录职责。

## 核心分层

- `src/nmn/graph`：图生成、Dijkstra 基线、JSON 持久化、指标计算、图可视化
- `src/nmn/datasets`：MoST / SUMO `.net.xml` 导入、标准化、数据集配置加载
- `src/nmn/loihi`：Brian2Loihi 波前路由、CPU 参考波前、parent trace、STDP、路径重建、动态重规划
- `src/nmn/localization`：Grid cells、Place cells、动态起点估计
- `src/nmn/noc`：NoC core 映射、packet trace、traffic table、Noxim 接口、代理指标
- `src/nmn/utils`：通用路径、配置、JSON、日志辅助函数

## 现有目录

- `experiments/`：只负责串联实验，不放核心算法
- `configs/`：实验配置文件
- `tests/`：单元测试和集成测试
- `docs/`：说明文档
- `data/`：外部数据集本地目录
- `results/`：实验输出目录
- `scripts/`：测试和清理脚本

## 设计原则

1. 核心算法放在 `src/nmn`。
2. `experiments/` 只做 CLI 编排。
3. 旧入口必须保留兼容 wrapper。
4. 文档统一使用中文。
5. 大图和真实数据导入通过配置控制，不在实验脚本中硬编码。

## 路径职责说明

### `graph`

负责 synthetic graph 生成、传统路径算法、图数据持久化、图结构统计和基础可视化。

### `datasets`

负责真实道路数据导入，尤其是 MoST / SUMO `.net.xml` 到标准 `nx.DiGraph` 的转换。

### `loihi`

负责 Loihi 风格的 SNN wavefront 路由、CPU 参考波前、STDP 与路径回溯。

### `localization`

负责把连续位置映射到图节点，支持 Grid/Place cells 的动态起点。

### `noc`

负责从脉冲到 NoC 数据包的映射，以及 Noxim 验证和统计。

## 兼容层

为了不破坏已有实验和测试，根目录原有包名仍可保留为兼容层：

- `graph/`
- `dataset_import/`
- `loihi_planner/`
- `localization/`
- `noc/`

这些包可以继续提供旧 import 路径，新代码建议逐步迁移到 `src/nmn/`。
