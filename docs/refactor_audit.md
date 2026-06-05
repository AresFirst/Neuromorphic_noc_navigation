# 当前结构审计

更新时间：2026-06-05
仓库：`neuromorphic_noc_navigation`

本文档记录当前项目结构和仍需注意的兼容边界。早期“整理前基线”已经不再准确：项目现在已有 `src/nmn` 标准包入口，同时保留根目录旧包作为兼容实现。

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
├── src/nmn/
└── tests/
```

## 2. 当前主线

当前优先目标是城市道路地图导航的软件层：

```text
MoST / SUMO net.xml
    -> 保留原始 SUMO geometry
    -> 临时 DiGraph 计算图
    -> SNN delay 编码
    -> Brian2Loihi wavefront
    -> parent trace 路径回溯
    -> SUMO edge/lane/polyline 反映射
    -> 原始 SUMO geometry overlay
```

关键实现：

- `src/nmn/sumo/geometry.py`
- `src/nmn/sumo/conversion.py`
- `src/nmn/sumo/dynamic.py`
- `src/nmn/sumo/visualization.py`
- `src/nmn/sumo/sumo_check.py`
- `experiments/run_most_sumo_overlay_navigation.py`
- `experiments/run_dynamic_sumo_overlay_navigation.py`
- `configs/most_sumo_overlay.yaml`
- `configs/dynamic_sumo_overlay.yaml`

## 3. 已完成的标准包入口

### `src/nmn/dynamic`

承载动态拥塞、车辆状态、重规划策略、SNN cost adapter 和动态可视化。

### `src/nmn/loihi`

提供静态 wrapper：

```text
src/nmn/loihi/backend.py
src/nmn/loihi/parent_trace.py
src/nmn/loihi/path_compare.py
src/nmn/loihi/path_reconstruction.py
src/nmn/loihi/wavefront.py
```

用途：

- 让新代码可以稳定使用 `nmn.loihi.*`。
- 解决 Pylance 对 `nmn.loihi.parent_trace` 等导入无法解析的问题。
- 避免重复实现 `loihi_planner/` 里的成熟逻辑。

### `src/nmn/sumo`

新增 SUMO 原始几何保留链路：

- 解析 `.net.xml` 的 junction、edge、lane shape。
- 生成临时 `networkx.DiGraph`，边属性保留 SUMO edge/lane/shape 映射。
- 将 SNN 输出路径映射回 SUMO edge ID 和 polyline。
- 使用 SUMO lane/edge geometry 绘制最终 overlay，不使用 NetworkX scatter 作为最终地图。
- 随机生成背景车辆，把车辆密度映射为 `delay_ms`、`state` 和 `threshold_penalty`，并输出动态帧/GIF。

## 4. 仍作为兼容实现保留的旧包

以下目录仍是实际功能的重要来源，不应删除：

- `graph/`
- `dataset_import/`
- `loihi_planner/`
- `localization/`
- `noc/`

当前策略是：

1. 新代码优先通过 `src/nmn` 导入。
2. 旧入口继续服务已有脚本和测试。
3. 迁移只做兼容 wrapper 或小步替换，避免一次性移动造成 import 断裂。

## 5. 当前实验入口

主要入口：

- `experiments/run_most_sumo_overlay_navigation.py`：MoST/SUMO 原始几何 overlay 导航。
- `experiments/run_dynamic_sumo_overlay_navigation.py`：随机车辆 + 拥塞 + Brian2Loihi wavefront 的动态 SUMO overlay 导航。
- `experiments/run_dynamic_city_navigation.py`：graph-level 动态城市导航。
- `experiments/run_most_import.py`：MoST `.net.xml` 到标准 `graph.json`。
- `experiments/run_most_navigation.py`：MoST graph-level 软件闭环导航。
- `experiments/run_loihi_wavefront.py`：通用 Brian2Loihi wavefront。
- `experiments/run_stdp_path_reconstruction.py`：STDP / parent trace 路径重建。
- `experiments/run_dynamic_start_and_relay.py`：动态起点与 relay gate。
- `experiments/run_toolchain_check.py`：工具链检查。

可选入口：

- `experiments/run_noc_validation.py`：NoC / Noxim 验证。
- `experiments/run_week1_toolchain_check.py`：旧工具链检查入口，保留兼容。
- `experiments/visualize_path_comparison.py`：旧路径对比展示入口。

## 6. 当前配置文件

- `configs/graph.yaml`
- `configs/brian2loihi.yaml`
- `configs/most.yaml`
- `configs/most_sumo_overlay.yaml`
- `configs/dynamic_sumo_overlay.yaml`
- `configs/dynamic_city_navigation.yaml`
- `configs/noxim.yaml`

注意：`configs/most_sumo_overlay.yaml` 默认指向 `datasets/MoSTScenario-master`，`configs/most.yaml` 默认指向 `data/datasets/MoSTScenario`。如果数据只存在一个位置，需要同步修改配置。

## 7. 风险点

1. Brian2Loihi 是强依赖，不能静默替换为普通 Brian2。
2. `networkx.DiGraph` 只适合计算层；最终 SUMO/MoST 地图可视化必须保留原始 geometry。
3. MoST 数据目录可能有 `datasets/MoSTScenario-master` 和 `data/datasets/MoSTScenario` 两种本地路径，运行前要核对 config。
4. `eclipse-sumo` Python wheel 在 macOS 上可能因 bundled dylib 签名被系统拒绝；可导入 `sumolib/traci` 不代表 `sumo` CLI 可运行。
5. 完整 `pytest` 可能受本地 Noxim 二进制状态影响；MoST/SUMO 软件层验证建议用 `pytest -k 'not noxim'`。
6. `graph.json` 序列化需要处理边属性 `source` / `target` 与 JSON 端点字段的命名冲突。

## 8. 建议后续整理

- 将 `dataset_import/` 中稳定的 SUMO/MoST 导入逻辑逐步迁移或包装到 `src/nmn/datasets`。
- 将 `graph/` 中稳定的生成、基线和序列化逻辑逐步包装到 `src/nmn/graph`。
- 保持 `src/nmn/sumo` 作为 SUMO 原始几何显示链路，不与 graph-level 导入混合。
- 将文档和 README 继续围绕“软件层城市导航主线 + 可选 NoC 验证”组织。
