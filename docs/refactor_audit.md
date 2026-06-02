# 重构审计报告

生成时间：2026-06-02  
仓库：`neuromorphic_noc_navigation`

说明：本文档记录的是整理前的基线状态，用于和后续的 `src/nmn` 结构对照。

## 1. 当前目录树

```text
neuromorphic_noc_navigation/
├── README.md
├── PROJECT_GUIDE.md
├── requirements.txt
├── configs/
├── dataset_import/
├── datasets/
├── docs/
├── experiments/
├── graph/
├── localization/
├── loihi_planner/
├── noc/
├── results/
├── scripts/
└── tests/
```

当前仓库已经具备完整实验链路，但代码主要分散在根目录包中，尚未统一到 `src/nmn/` 的标准结构。

## 2. 当前主要模块清单

- `graph/`：synthetic graph、Dijkstra 基线、图序列化、指标、可视化
- `dataset_import/`：MoST / SUMO `.net.xml` 导入与标准化
- `loihi_planner/`：Brian2Loihi 后端、波前路由、parent trace、STDP、路径重建、动态重规划
- `localization/`：Grid cells、Place cells、动态起点
- `noc/`：NoC core mapping、packet trace、traffic table、Noxim 接口、代理指标
- `experiments/`：各周实验入口脚本
- `docs/`：现有说明文档
- `tests/`：单元测试与集成测试

## 3. 重复文件或功能重叠文件

- `graph/` 与 `dataset_import/` 都提供图构建入口，但面向对象不同：前者是 synthetic graph，后者是公开道路数据导入。
- `loihi_planner/path_compare.py` 与 `experiments/visualize_path_comparison.py` 都涉及路径对比可视化，前者负责数值对比，后者负责展示。
- `noc/noc_experiment.py` 与 `experiments/run_noc_validation.py` 都在编排 NoC 验证流程，前者偏函数级，后者偏 CLI 级。
- `README.md`、`PROJECT_GUIDE.md`、`docs/loihi_planner_demos.md` 的内容部分重叠，且语言风格不完全统一。

## 4. 命名不一致的文件

- 根目录包名仍是 `graph`、`dataset_import`、`loihi_planner`、`noc`、`localization`，与目标结构 `src/nmn/...` 不一致。
- `noc/noc_proxy_metrics.py` 与目标结构中的 `proxy_metrics.py` 命名不一致。
- `noc/noxim_wrapper.py` 与目标结构中的 `noxim.py` 命名不一致。
- `graph/complex_graph_generator.py` 与目标结构中的 `synthetic.py` 命名不一致。
- 现有文档仍混用中文和英文标题，未统一为中文。

## 5. 可以移动但不应删除的文件

- `graph/complex_graph_generator.py`
- `graph/graph_baseline.py`
- `graph/graph_io.py`
- `graph/graph_metrics.py`
- `graph/visualization.py`
- `dataset_import/` 全部文件
- `loihi_planner/` 相关核心文件
- `localization/` 相关文件
- `noc/` 相关文件
- `experiments/` 所有入口脚本

这些文件是当前实验链路的实际实现，不应删除，只适合迁移或建立兼容包装。

## 6. 已有实验脚本入口

- `experiments/run_week1_toolchain_check.py`
- `experiments/run_graph_baseline.py`
- `experiments/run_most_import.py`
- `experiments/run_most_navigation.py`
- `experiments/run_loihi_wavefront.py`
- `experiments/run_stdp_path_reconstruction.py`
- `experiments/run_dynamic_start_and_relay.py`
- `experiments/run_noc_validation.py`
- `experiments/visualize_path_comparison.py`

## 7. 已有配置文件

- `configs/graph.yaml`
- `configs/brian2loihi.yaml`
- `configs/noxim.yaml`
- `configs/most.yaml`

## 8. 已有测试文件

当前测试覆盖图生成、导入、Loihi 波前、路径重建、动态起点、NoC、MoST 导入与软件闭环导航等场景。

## 9. 可能会被重构影响的风险点

1. 现有脚本和测试大量依赖根目录包名，直接改目录会导致 import 链断裂。
2. Brian2Loihi 后端检测是强依赖，不能回退成普通 Brian2。
3. MoST 导入会读取本地大 XML 文件，移动数据目录或改默认路径会影响导入命令。
4. `graph.json` 序列化里存在保留字段冲突风险，边属性 `source` 需要特别处理。
5. `pytest` 里已有许多回归测试，迁移后必须保持旧入口兼容。
6. 文档语言统一为中文时，要避免把用户提供的命令示例改坏。

## 10. 建议的新目录结构

建议采用以下分层：

```text
src/nmn/
├── graph/
├── datasets/
├── loihi/
├── localization/
├── noc/
└── utils/
```

配合：

```text
experiments/
configs/
tests/
docs/
data/
results/
scripts/
```

建议策略：

- `src/nmn` 作为新标准包名；
- 根目录旧包保留兼容 wrapper；
- 实验脚本保持 CLI 不变；
- 文档统一中文；
- `README.md` 只保留项目概览和最常用命令。
