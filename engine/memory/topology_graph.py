"""
金枢 3.0 (Jin-Shu OS) - 数据中心 L1-L7 全栈拓扑知识图谱 (Topology Graph)
========================================================================
消除传统数据中心 L1 (动力暖通安防) 与 L3-L7 (云原生与业务) 的数据孤岛。
构建覆盖供电拓扑、制冷拓扑、物理空间及云主机依赖的有向关联图。
支持多跳 (Multi-Hop) 因果追踪：
  - 上游溯源：机柜过热 -> 溯源至对应 PDU、列头柜与对应冷水支路。
  - 下游影响：宿主机宕机 -> 穿透计算受影响的云主机、容器及上层金融业务 SLA。
"""

from typing import Dict, Any, List, Set
from dataclasses import dataclass, field


@dataclass
class TopologyNode:
    """拓扑图实体节点"""
    id: str
    name: str
    layer: str  # L1_Power, L1_HVAC, L2_Spatial, L3_Compute, L4_Network, L7_App
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TopologyEdge:
    """拓扑图关联边"""
    source: str
    target: str
    relation: str  # powers, cools, houses, hosts, depends_on


class DatacenterTopologyGraph:
    """全栈拓扑关系中枢 (In-Memory GraphRAG Engine)"""

    def __init__(self):
        self.nodes: Dict[str, TopologyNode] = {}
        self.out_edges: Dict[str, List[TopologyEdge]] = {}
        self.in_edges: Dict[str, List[TopologyEdge]] = {}
        self._build_default_datacenter_topology()

    def add_node(self, node_id: str, name: str, layer: str, properties: Dict[str, Any] = None):
        self.nodes[node_id] = TopologyNode(id=node_id, name=name, layer=layer, properties=properties or {})
        if node_id not in self.out_edges:
            self.out_edges[node_id] = []
        if node_id not in self.in_edges:
            self.in_edges[node_id] = []

    def add_edge(self, source: str, target: str, relation: str):
        edge = TopologyEdge(source=source, target=target, relation=relation)
        self.out_edges.setdefault(source, []).append(edge)
        self.in_edges.setdefault(target, []).append(edge)

    def _build_default_datacenter_topology(self):
        """构建中国金电典型生产数据中心 (A区示范机房) 的 L1-L7 孪生骨架"""
        # 1. L1 动力系统 (Power Loop)
        self.add_node("UPS-A01", "主配电 UPS 01", "L1_Power", {"capacity_kva": 800, "redundancy": "2N"})
        self.add_node("PDU-A01", "列头精密配电柜 A01", "L1_Power", {"rated_current": "160A"})
        self.add_node("PDU-A02", "列头精密配电柜 A02", "L1_Power", {"rated_current": "160A"})
        self.add_edge("UPS-A01", "PDU-A01", "powers")
        self.add_edge("UPS-A01", "PDU-A02", "powers")

        # 2. L1 暖通制冷 (HVAC Loop)
        self.add_node("CHILLER-01", "1号离心冷水机组", "L1_HVAC", {"cop": 5.8, "supply_temp": 12.0})
        self.add_node("CRAC-A01", "A区精密空调 01", "L1_HVAC", {"airflow_m3h": 12000, "status": "running"})
        self.add_node("CRAC-A02", "A区精密空调 02", "L1_HVAC", {"airflow_m3h": 12000, "status": "running"})
        self.add_edge("CHILLER-01", "CRAC-A01", "cools")
        self.add_edge("CHILLER-01", "CRAC-A02", "cools")

        # 3. L2 空间微环境 (Spatial Aisle & Racks)
        self.add_node("AISLE-A", "A区封闭冷通道", "L2_Spatial", {"delta_p_pa": 22.5})
        self.add_node("RACK-A01", "A区01号高密计算机柜", "L2_Spatial", {"rated_kw": 12.0})
        self.add_node("RACK-A02", "A区02号核心交易机柜", "L2_Spatial", {"rated_kw": 14.5})
        self.add_node("RACK-A03", "A区03号分布式存储机柜", "L2_Spatial", {"rated_kw": 10.0})

        self.add_edge("CRAC-A01", "AISLE-A", "cools")
        self.add_edge("AISLE-A", "RACK-A01", "cools")
        self.add_edge("AISLE-A", "RACK-A02", "cools")
        self.add_edge("AISLE-A", "RACK-A03", "cools")
        self.add_edge("PDU-A01", "RACK-A01", "powers")
        self.add_edge("PDU-A01", "RACK-A02", "powers")
        self.add_edge("PDU-A02", "RACK-A03", "powers")

        # 4. L3 计算底盘与物理主机 (Compute Infrastructure)
        self.add_node("SVR-001", "物理服务器 001 (Node-01)", "L3_Compute", {"cpu_cores": 128, "mem_gb": 512})
        self.add_node("SVR-002", "物理服务器 002 (Node-02)", "L3_Compute", {"cpu_cores": 128, "mem_gb": 512})
        self.add_node("SVR-003", "物理服务器 003 (Node-03)", "L3_Compute", {"cpu_cores": 128, "mem_gb": 512})

        self.add_edge("RACK-A02", "SVR-001", "houses")
        self.add_edge("RACK-A02", "SVR-002", "houses")
        self.add_edge("RACK-A03", "SVR-003", "houses")

        # 5. L7 虚拟化、数据库与核心金融交易业务 (Workloads & SLAs)
        self.add_node("VM-PAYMENT-01", "核心跨行清算主实例", "L7_App", {"tier": "TIER_1_CRITICAL", "sla_latency_ms": 10})
        self.add_node("VM-PAYMENT-02", "核心跨行清算备实例", "L7_App", {"tier": "TIER_1_CRITICAL", "sla_latency_ms": 10})
        self.add_node("DB-SETTLE-CLUSTER", "分布式清算数据库集群", "L7_App", {"quorum_min": 2, "nodes": 3})

        self.add_edge("SVR-001", "VM-PAYMENT-01", "hosts")
        self.add_edge("SVR-002", "VM-PAYMENT-02", "hosts")
        self.add_edge("SVR-003", "DB-SETTLE-CLUSTER", "hosts")
        self.add_edge("VM-PAYMENT-01", "DB-SETTLE-CLUSTER", "depends_on")

    def trace_upstream_cause(self, target_id: str, depth: int = 2) -> List[Dict[str, Any]]:
        """
        上游溯源查询：沿着依赖的入边 (in_edges) 逆向追溯物理与供电动环诱因。
        例如：SVR-001 异常 -> 找到 RACK-A02 -> 找到 PDU-A01 和 AISLE-A -> 找到 CRAC-A01
        """
        visited: Set[str] = set()
        results: List[Dict[str, Any]] = []

        def dfs(current: str, current_depth: int):
            if current_depth > depth or current in visited:
                return
            visited.add(current)
            for edge in self.in_edges.get(current, []):
                src_node = self.nodes.get(edge.source)
                if src_node:
                    results.append({
                        "hop": current_depth,
                        "node_id": src_node.id,
                        "name": src_node.name,
                        "layer": src_node.layer,
                        "relation": edge.relation,
                        "properties": src_node.properties
                    })
                    dfs(edge.source, current_depth + 1)

        dfs(target_id, 1)
        return results

    def trace_downstream_impact(self, target_id: str, depth: int = 2) -> List[Dict[str, Any]]:
        """
        下游影响度评估：沿着输出边 (out_edges) 正向探测对虚拟机与金融业务 SLA 的连锁冲击。
        例如：PDU-A01 掉电 -> 冲击 RACK-A01/A02 -> 冲击 SVR-001/002 -> 威胁 VM-PAYMENT-01
        """
        visited: Set[str] = set()
        results: List[Dict[str, Any]] = []

        def dfs(current: str, current_depth: int):
            if current_depth > depth or current in visited:
                return
            visited.add(current)
            for edge in self.out_edges.get(current, []):
                tgt_node = self.nodes.get(edge.target)
                if tgt_node:
                    results.append({
                        "hop": current_depth,
                        "node_id": tgt_node.id,
                        "name": tgt_node.name,
                        "layer": tgt_node.layer,
                        "relation": edge.relation,
                        "properties": tgt_node.properties
                    })
                    dfs(edge.target, current_depth + 1)

        dfs(target_id, 1)
        return results

    def get_summary_context(self, target_id: str) -> str:
        """为智能体生成紧凑的拓扑因果图谱摘要文本"""
        if target_id not in self.nodes:
            return f"拓扑图谱中未收录目标实体: {target_id}"

        node = self.nodes[target_id]
        up = self.trace_upstream_cause(target_id, depth=2)
        down = self.trace_downstream_impact(target_id, depth=2)

        lines = [f"### 🌐 空间与物理拓扑因果孪生 [{node.name} ({node.id}) - {node.layer}]"]
        if up:
            lines.append("⬆️ [上游供电与制冷诱因链路]:")
            for item in up:
                lines.append(f"  └─ Hop {item['hop']}: {item['name']} ({item['layer']}) - 关联: {item['relation']}")
        if down:
            lines.append("⬇️ [下游受影响主机与金融业务 SLA 链路]:")
            for item in down:
                lines.append(f"  └─ Hop {item['hop']}: {item['name']} ({item['layer']}) - 影响: {item['relation']}")

        return "\n".join(lines)


# 全局单例拓扑图
global_topology_graph = DatacenterTopologyGraph()
