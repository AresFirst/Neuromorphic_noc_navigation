# 运行手册

本文档给出当前项目推荐运行顺序。当前主目标是 MoST/SUMO 城市道路地图的软件层导航和原始几何 overlay 可视化；NoC / Noxim 不属于必需步骤。

## 1. 安装 Python 项目

```bash
pip install -e .
python -m pip install -r requirements.txt
```

Brian2Loihi 必须在当前环境可导入。项目不会静默回退到普通 Brian2。

## 2. 检查 Brian2Loihi

```bash
python experiments/run_toolchain_check.py
```

也可以直接检查：

```bash
python - <<'PY'
from loihi_planner.backend_check import check_brian2loihi_available
print(check_brian2loihi_available())
PY
```

期望 `available=True`。

## 3. 准备 MoST 数据

当前仓库示例数据位于：

```text
datasets/MoSTScenario-master/
```

如果本地没有 MoST，下载到任一目录后修改对应 config：

```bash
git clone https://github.com/lcodeca/MoSTScenario.git data/datasets/MoSTScenario
```

注意：

- `configs/most_sumo_overlay.yaml` 默认使用 `datasets/MoSTScenario-master`。
- `configs/most.yaml` 默认使用 `data/datasets/MoSTScenario`；如果数据放在 `datasets/MoSTScenario-master`，请同步修改 `dataset.root_dir`。

## 4. 安装并检查 Eclipse SUMO

推荐使用官方 macOS package、Homebrew tap 或源码安装。默认 `homebrew/core` 没有 Eclipse SUMO formula。

```bash
brew tap dlr-ts/sumo
brew install sumo
```

如果 `sumo` 不在 `PATH`：

```bash
export SUMO_HOME=/path/to/eclipse-sumo
export SUMO_BINARY="$SUMO_HOME/bin/sumo"
export SUMO_GUI_BINARY="$SUMO_HOME/bin/sumo-gui"
```

检查：

```bash
sumo --version
sumo-gui datasets/MoSTScenario-master/scenario/most.sumocfg
```

不要把 conda-forge 上名为 `sumo` 的材料科学工具包当成 Eclipse SUMO。项目的 SUMO 检测会调用 `sumo --version` 并报告同名错误命令。

如果使用 `pip install eclipse-sumo`，macOS 可能因为 bundled dylib 签名拒绝运行 `sumo`/`sumo-gui`。这种情况下 `sumolib/traci` 可能可导入，但 SUMO CLI 仍不可用，应改用官方 package、Homebrew tap 或源码安装。

## 5. 运行 MoST/SUMO 原始几何 overlay 导航

正式运行：

```bash
python experiments/run_most_sumo_overlay_navigation.py \
  --config configs/most_sumo_overlay.yaml
```

如果当前机器 SUMO CLI 暂时不可用，但要先验证 Python 软件链路：

```bash
python experiments/run_most_sumo_overlay_navigation.py \
  --config configs/most_sumo_overlay.yaml \
  --skip-sumo-load-check
```

输出：

```text
results/most_sumo_overlay/planning_summary.json
results/most_sumo_overlay/sumo_route.json
results/most_sumo_overlay/temporary_planning_graph.json
results/most_sumo_overlay/route_overlay.png
results/most_sumo_overlay/route_overlay_zoom.png
```

验证：

- `planning_summary.json` 中 `success=true`。
- `graph_is_temporary=true`。
- `visualization_source=original_sumo_geometry`。
- `route_overlay.png` 和 `route_overlay_zoom.png` 能看到 SUMO 道路线形和红色路径 overlay。

## 6. 导入 MoST 为 graph-level 数据

动态导航和旧 MoST 导航入口读取标准 `graph.json`：

```bash
python experiments/run_most_import.py --config configs/most.yaml
```

输出：

```text
results/most/graph.json
results/most/graph_metrics.json
results/most/preview.png
results/most/import_summary.json
```

注意：这个导入会把 MoST 转成 `networkx.DiGraph` 作为计算图，适合 graph-level 实验；最终 SUMO 原始几何 overlay 应使用第 5 步的入口。

## 7. 运行软件闭环 MoST 导航

```bash
python experiments/run_most_navigation.py \
  --config configs/most.yaml \
  --loihi-config configs/brian2loihi.yaml \
  --output results/most/navigation \
  --num-pairs 3 \
  --seed 0
```

输出：

```text
results/most/navigation/navigation_summary.json
results/most/navigation/navigation_path_compare.png
```

这个入口是 graph-level 导航，可用于路径验证，但最终显示不保留完整 SUMO lane geometry。

## 8. 运行动态城市导航

先确保 `results/most/graph.json` 存在：

```bash
python experiments/run_most_import.py --config configs/most.yaml
```

再运行：

```bash
python experiments/run_dynamic_city_navigation.py \
  --config configs/dynamic_city_navigation.yaml
```

输出：

```text
results/dynamic_city_navigation/dynamic_step_logs.csv
results/dynamic_city_navigation/dynamic_summary.json
results/dynamic_city_navigation/congestion_events.json
results/dynamic_city_navigation/final_route.json
results/dynamic_city_navigation/frames/
results/dynamic_city_navigation/preview_final.png
```

限制：

- 这是 graph-level 动态闭环，不是真实车辆动力学。
- 没有接 CARLA。
- 没有接 SUMO TraCI。
- “实时”指仿真闭环，不是硬实时。

## 9. Synthetic graph 基线

```bash
python experiments/run_graph_baseline.py --config configs/graph.yaml --output results/week2
```

## 10. Loihi wavefront / STDP / relay demo

```bash
python experiments/run_loihi_wavefront.py \
  --graph results/week2/graph.json \
  --config configs/brian2loihi.yaml \
  --output results/week3 \
  --num-pairs 10 \
  --seed 0

python experiments/run_stdp_path_reconstruction.py \
  --graph results/week2/graph.json \
  --config configs/brian2loihi.yaml \
  --output results/week4 \
  --num-pairs 20 \
  --seed 0

python experiments/run_dynamic_start_and_relay.py \
  --graph results/week2/graph.json \
  --config configs/brian2loihi.yaml \
  --output results/week5 \
  --seed 0
```

## 11. 可选 NoC / Noxim 验证

NoC 验证不是城市道路导航主线。需要本地 Noxim 可用时再运行：

```bash
python experiments/run_noc_validation.py \
  --graph results/week2/graph.json \
  --loihi-config configs/brian2loihi.yaml \
  --noc-config configs/noxim.yaml \
  --output results/week6 \
  --num-pairs 20 \
  --seed 0
```

如果 Noxim 路径不可用，脚本应将 Noxim 状态标记为 skipped 或 failed，不应影响 MoST/SUMO 软件导航主线。

## 12. 测试

推荐测试：

```bash
python -m pytest -q -k 'not noxim'
```

SUMO overlay 相关测试：

```bash
python -m pytest tests/test_sumo_geometry_overlay.py tests/test_sumo_check.py -q
```

完整测试：

```bash
python -m pytest -q
```

当前本地如果存在 Noxim 真实二进制但配置不匹配，完整测试可能在 Noxim 集成测试失败；这与 MoST/SUMO 软件层导航无关。

## 排障

- `ModuleNotFoundError: nmn...`：确认已 `pip install -e .`，或从仓库根目录运行实验脚本。
- `Brian2Loihi is required`：当前 Python 环境没有可用 `brian2_loihi`。
- `SUMO map load check failed`：先运行 `sumo --version`，确认是 Eclipse SUMO，不是同名错误包。
- `MoST .net.xml not found`：检查 config 中的 MoST root path。
- overlay 图片太淡或看不出道路：当前 `src/nmn/sumo/visualization.py` 默认使用较深道路底图，并输出全图与路线局部图；重新运行第 5 步即可。
