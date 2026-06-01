"""测试包 (tests)。

包含所有模块的单元测试，覆盖:
- 后端检测 (test_backend_check)
- 图生成器 (test_complex_graph_generator)
- Dijkstra 基线 (test_graph_baseline)
- 图 IO (test_graph_io)
- Loihi demos (test_loihi_demos)
- Loihi 波前 (test_loihi_wavefront)
- NoC 工具 (test_noc_utils)
- 父节点追踪 (test_parent_trace)
- 路径重建 (test_path_reconstruction)
- 脉冲记录 (test_spike_trace)
- STDP 对比 (test_stdp_trace_compare)
- 参考波前 (test_wavefront_reference)

运行: pytest  (conftest.py 自动配置 sys.path 和 matplotlib)
"""
