# 运行手册

本文档给出从零开始的推荐运行顺序。

## 1. 安装

```bash
pip install -e .
```

## 2. 运行测试

```bash
pytest
```

## 3. 生成合成图基线

```bash
python experiments/run_graph_baseline.py --config configs/graph.yaml --output results/week2
```

## 4. 运行 Loihi wavefront

```bash
python experiments/run_loihi_wavefront.py \
  --graph results/week2/graph.json \
  --config configs/brian2loihi.yaml \
  --output results/week3 \
  --num-pairs 10 \
  --seed 0
```

## 5. 运行 STDP 路径重建

```bash
python experiments/run_stdp_path_reconstruction.py \
  --graph results/week2/graph.json \
  --config configs/brian2loihi.yaml \
  --output results/week4 \
  --num-pairs 20 \
  --seed 0
```

## 6. 运行动态起点与 relay

```bash
python experiments/run_dynamic_start_and_relay.py \
  --graph results/week2/graph.json \
  --config configs/brian2loihi.yaml \
  --output results/week5 \
  --seed 0
```

## 7. 运行软件闭环的 MoST 导航

```bash
python experiments/run_most_navigation.py \
  --config configs/most.yaml \
  --loihi-config configs/brian2loihi.yaml \
  --output results/most/navigation \
  --num-pairs 3 \
  --seed 0
```

## 8. 可选：导入 MoST 原始地图

```bash
python experiments/run_most_import.py --config configs/most.yaml
```

导入后会生成 `results/most/graph.json`，可直接供后续实验复用。

## 9. 可选：运行 NoC 验证

```bash
python experiments/run_noc_validation.py \
  --graph results/week2/graph.json \
  --loihi-config configs/brian2loihi.yaml \
  --noc-config configs/noxim.yaml \
  --output results/week6 \
  --num-pairs 20 \
  --seed 0
```

## 排障建议

- 先确认 `python -m pytest` 通过。
- 再确认 `python experiments/run_graph_baseline.py ...` 产物正常。
- 如果 Brian2Loihi 不可用，Loihi 相关脚本会明确报错或返回 skipped，不会伪造结果。
- 如果使用 MoST，请先检查本地是否已下载 `MoSTScenario`。
