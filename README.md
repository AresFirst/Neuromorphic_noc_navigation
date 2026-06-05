# Neuromorphic SUMO Navigation

这是一个精简后的城市道路地图导航项目。当前只保留一条可运行主线：

```text
MoST/SUMO 原始地图
    -> 解析 SUMO .net.xml 道路几何
    -> 临时 DiGraph 计算层
    -> Brian2Loihi wavefront 路径规划
    -> 随机背景车辆与拥塞更新
    -> 动态重规划
    -> 回写 SUMO road/lane geometry
    -> 在原始地图上叠加显示路径、车辆、拥塞和脉冲传播
```

本版本删除了旧的硬件互连验证逻辑、合成图生成入口、Brian2Loihi 小型 demo、STDP/relay demo、旧实验脚本和分散文档。`networkx.DiGraph` 只作为临时计算结构存在，不作为主地图格式，也不生成最终地图可视化。最终图像和 GIF 始终基于 SUMO `.net.xml` 中的原始 lane shape / edge geometry。

## 当前保留内容

```text
.
├── README.md
├── configs/
│   ├── brian2loihi.yaml
│   └── dynamic_sumo_overlay.yaml
├── datasets/
│   └── MoSTScenario-master/
│       └── scenario/
│           ├── most.sumocfg
│           └── in/most.net.xml
├── experiments/
│   └── run_dynamic_sumo_overlay_navigation.py
├── loihi_planner/
│   ├── _brian2_runner.py
│   ├── backend_check.py
│   ├── loihi_config.py
│   ├── loihi_wavefront.py
│   ├── parent_trace.py
│   ├── path_compare.py
│   ├── path_reconstruction.py
│   └── wavefront_reference.py
├── src/nmn/
│   ├── loihi/__init__.py
│   └── sumo/
│       ├── conversion.py
│       ├── dynamic.py
│       ├── geometry.py
│       ├── sumo_check.py
│       └── visualization.py
└── tests/
    ├── test_sumo_check.py
    ├── test_sumo_dynamic.py
    └── test_sumo_geometry_overlay.py
```

## 模块职责

- `src/nmn/sumo/geometry.py`：读取 SUMO `.net.xml`，保留 junction、edge、lane shape。
- `src/nmn/sumo/conversion.py`：把 SUMO 几何临时转换为规划用 `DiGraph`，并把 SNN 输出路径映射回 SUMO road/lane。
- `src/nmn/sumo/dynamic.py`：生成随机车辆，按车辆密度更新拥堵、阻塞、边延迟和节点阈值惩罚。
- `src/nmn/sumo/visualization.py`：在原始 SUMO 道路几何上绘制动态帧、路线、车辆、拥塞和 wavefront。
- `loihi_planner/loihi_wavefront.py`：运行 Brian2Loihi wavefront，把道路边延迟编码为突触延迟。
- `experiments/run_dynamic_sumo_overlay_navigation.py`：当前唯一主入口。

## 环境安装

建议继续使用已有的 `brian2loihi` conda 环境：

```bash
conda activate brian2loihi
pip install -r requirements.txt
pip install -e .
```

如果你要执行真实 SUMO 地图加载检查，还需要安装 SUMO 并确保命令行可用：

```bash
sumo --version
sumo-gui --version
```

macOS 上可以用 Homebrew 安装：

```bash
brew install sumo
```

如果本机 SUMO 命令暂时不可用，可以先使用 `--skip-sumo-load-check` 跑通软件层闭环。这个参数只跳过 SUMO 可执行文件加载检查，不影响 `.net.xml` 几何解析、Brian2Loihi 规划和地图 overlay 输出。

## 运行主流程

在项目根目录运行：

```bash
python experiments/run_dynamic_sumo_overlay_navigation.py \
  --config configs/dynamic_sumo_overlay.yaml \
  --skip-sumo-load-check
```

如果使用当前机器上的 conda 解释器，也可以直接运行：

```bash
/opt/anaconda3/envs/brian2loihi/bin/python experiments/run_dynamic_sumo_overlay_navigation.py \
  --config configs/dynamic_sumo_overlay.yaml \
  --skip-sumo-load-check
```

如果 SUMO 已安装并能正常加载 MoST 场景，去掉 `--skip-sumo-load-check`：

```bash
python experiments/run_dynamic_sumo_overlay_navigation.py \
  --config configs/dynamic_sumo_overlay.yaml
```

## 输出文件

默认输出目录由 `configs/dynamic_sumo_overlay.yaml` 控制：

```text
results/dynamic_sumo_overlay/
├── dynamic_summary.json
├── dynamic_step_logs.json
├── dynamic_navigation.gif
├── wavefront_all.gif
├── latest_sumo_route.json
├── final_background_vehicles.json
├── initial_temporary_planning_graph.json
├── dynamic_frames/
└── wavefront_frames/
```

关键文件含义：

- `dynamic_summary.json`：一次运行的总体统计，包括起终点、重规划次数、脉冲数、输出路径。
- `dynamic_step_logs.json`：每个动态步的当前位置、是否重规划、拥塞边、阻塞边和路线。
- `dynamic_navigation.gif`：车辆、拥塞、当前路线随时间变化的动态地图。
- `wavefront_all.gif`：Brian2Loihi 脉冲波前在地图上的传播动画。
- `latest_sumo_route.json`：最终一次成功规划映射回 SUMO edge/lane geometry 的路线。
- `initial_temporary_planning_graph.json`：调试用临时计算图，不是最终地图表示。

## 可视化图例

- 深色细线：原始 SUMO 道路几何。
- 红色粗线：当前规划路线。
- 蓝色点：随机背景车辆。
- 橙色线：拥堵道路。
- 黑色线：阻塞道路。
- 青色线/彩色点：Brian2Loihi wavefront 已传播到的边和神经元。
- 绿色圆点：当前位置。
- 紫色星标：目标位置。

## 配置说明

`configs/dynamic_sumo_overlay.yaml` 是主配置：

- `map.root_dir`：MoST 数据集根目录。
- `map.netxml_path`：指定 SUMO `.net.xml`；为 `null` 时自动在 `root_dir` 下寻找主地图。
- `map.sumocfg_path`：SUMO 场景配置文件，用于地图加载检查。
- `planning.max_nodes`：从 MoST 主图中裁剪出的最大规划节点数。数值越大地图越完整，但 Brian2Loihi 运行更慢。
- `planning.max_steps`：动态导航步数上限。
- `planning.replan_interval`：固定重规划间隔。
- `traffic.num_vehicles`：随机背景车辆数量。
- `traffic.num_hotspots`：车辆热点边数量，用于稳定制造可见拥堵。
- `congestion.congested_density`：超过该密度后边延迟升高。
- `congestion.blocked_density`：超过该密度后边变为阻塞，SNN 不再通过该边传播。
- `congestion.delay_factor`：拥塞边延迟放大系数。
- `congestion.threshold_penalty_ms`：拥塞映射到目标节点的额外阈值/延迟惩罚。
- `visualization.wavefront_frames_per_replan`：每次重规划输出多少张 wavefront 帧。
- `output.output_dir`：结果目录。

`configs/brian2loihi.yaml` 控制 SNN 参数：

- `threshold`：神经元发放阈值。
- `weight`：突触权重，当前默认大于阈值，保证单次前驱脉冲可触发后继神经元。
- `refractory_ms`：不应期，默认足够大，使每个神经元只记录首次到达。
- `seed`：Brian2Loihi 运行种子。

## 动态拥塞到 SNN 的映射

当前实现是软件层近似，不依赖 SUMO TraCI 实时交通仿真：

1. 在临时规划图边上随机生成背景车辆。
2. 每一步车辆沿道路边前进，并在路口随机选择下一条非阻塞出边。
3. 按 `车辆数 / 边容量` 计算密度。
4. 密度超过 `congested_density` 时，提高该边 `delay_ms`。
5. 密度超过 `blocked_density` 时，把边标记为 `blocked`。
6. 拥塞还会增加目标节点的 `threshold_penalty`，并折算为进入该节点的额外延迟。
7. Brian2Loihi wavefront 在下一次重规划时读取新的 `delay_ms` 和 `blocked` 状态，路线会随交通情况变化。

## 运行测试

```bash
python -m pytest -q
```

当前测试只覆盖保留主线：

- SUMO `.net.xml` 几何解析。
- 临时规划图和 SUMO 路线映射。
- 原始地图 overlay 可视化。
- 随机车辆、拥塞、阻塞和 GIF 输出。
- SUMO 命令可用性检查函数。

## 设计约束

- 不保留旧的硬件互连验证逻辑。
- 不保留合成图生成器和旧 graph baseline 实验。
- 不保留 Brian2Loihi 小型 demo。
- 不把 `DiGraph` 当作主地图格式。
- 不输出仅包含节点散点和边线段的 NetworkX 风格地图。
- 不破坏 MoST/SUMO 原始道路几何。
- `DiGraph` 只用于计算、SNN 编码和调试 JSON。

## 后续优化方向

这个精简版本的边界已经足够清楚，后续可以在此基础上逐步增强：

- 用 SUMO TraCI 替换当前 Python 随机车辆模型，读取真实车辆位置和道路速度。
- 把拥塞映射从简单 `delay_ms` 放大升级为更细的阈值、电流、延迟或抑制机制。
- 增加交互式前端或地图播放器，实时播放 wavefront 和重规划过程。
- 扩大 `planning.max_nodes`，并针对 Brian2Loihi 后端做批量突触构建优化。
