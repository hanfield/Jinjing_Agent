from engine.memory.topology_graph import DatacenterTopologyGraph


def test_topology_graph_initialization():
    graph = DatacenterTopologyGraph()
    assert "UPS-A01" in graph.nodes
    assert "CRAC-A01" in graph.nodes
    assert "RACK-A02" in graph.nodes
    assert "SVR-001" in graph.nodes
    assert "VM-PAYMENT-01" in graph.nodes


def test_upstream_cause_tracing():
    graph = DatacenterTopologyGraph()
    # 溯源 SVR-001 的上游动力与机架环境
    up = graph.trace_upstream_cause("SVR-001", depth=2)
    node_ids = [item["node_id"] for item in up]
    # SVR-001 上游应该追溯到 RACK-A02
    assert "RACK-A02" in node_ids


def test_downstream_impact_tracing():
    graph = DatacenterTopologyGraph()
    # 探测 SVR-001 宕机对下游业务的冲击
    down = graph.trace_downstream_impact("SVR-001", depth=2)
    node_ids = [item["node_id"] for item in down]
    # SVR-001 下游承载了核心跨行清算主实例 VM-PAYMENT-01
    assert "VM-PAYMENT-01" in node_ids


def test_topology_summary_context():
    graph = DatacenterTopologyGraph()
    summary = graph.get_summary_context("RACK-A02")
    assert "RACK-A02" in summary
    assert "上游供电与制冷诱因链路" in summary
    assert "下游受影响主机与金融业务 SLA 链路" in summary
