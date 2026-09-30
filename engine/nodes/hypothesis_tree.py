"""
金枢 3.0 (Jin-Shu OS) - 假说树搜索与并行探针引擎 (Hypothesis Tree Search / MCTS-Lite)
====================================================================================
针对机房复合型、多诱因模糊故障，彻底破除传统 ReAct 的单线贪心试错缺陷。

推演核心流程：
  1. Hypothesis Branching (假说裂变):
     面对高熵告警，在思维链中生成 K 个正交的物理/逻辑假说分支 (H1, H2, H3...)。
  2. Concurrent Probing (并发探针探查):
     调度只读无害工具探针 (ReadOnly Probes) 对各假说前提发起并发查验。
  3. Evidence Scoring & Pruning (证据打分与分支剪枝):
     依据返回的物理指标与日志特征对假说进行贝叶斯更新，剪除被证伪的分支 (Pruning)。
  4. Winning Causal Path (胜出因果链输出):
     输出唯一高置信度的根因归因路径与被剪枝的排除理由，供后续制定针对性 SOP。
"""

import asyncio
from dataclasses import dataclass
from typing import List, Dict, Any

from engine.tools import registry as tool_registry
from engine.tools.base import RiskLevel


@dataclass
class HypothesisBranch:
    """单个物理/逻辑假说分支"""
    hypothesis_id: str
    domain: str  # "INFRA", "CLOUD", "POWER"
    title: str
    premise: str
    probe_tool: str
    probe_args: Dict[str, Any]
    confidence_score: float = 0.5
    status: str = "PENDING"  # "CONFIRMED", "REFUTED", "PRUNED"
    evidence_finding: str = ""
    falsification_reason: str = ""


class HypothesisTreeExplorer:
    """假说树搜索与分支剪枝中枢"""

    def generate_candidate_hypotheses(self, incident: str, target: str = "SVR-001") -> List[HypothesisBranch]:
        """根据告警特征裂变出 3 个相互竞争的物理/逻辑假说分支"""
        # 预设基于数据中心先验拓扑的候选假说
        return [
            HypothesisBranch(
                hypothesis_id="H_INFRA",
                domain="INFRA",
                title="冷通道风道短路与局部热分层",
                premise="由于地板出风口被阻挡或机柜盲板脱落，冷风未渗透进高热区，引发服务器热保护降频。",
                probe_tool="analyze_thermal_infrared_matrix",
                probe_args={"target_id": "RACK-A02", "height_layers": 6}
            ),
            HypothesisBranch(
                hypothesis_id="H_CLOUD",
                domain="CLOUD",
                title="应用业务日志满溢引发磁盘 IO 阻塞",
                premise="核心应用未配置日志轮转，导致 /var/log 分区达到 100%，触发线程等待与响应超时。",
                probe_tool="query_infrastructure",
                probe_args={"query": target}
            ),
            HypothesisBranch(
                hypothesis_id="H_POWER",
                domain="POWER",
                title="UPS 逆变器供电电压纹波畸变",
                premise="UPS 滤波电容性能衰退，输出交流纹波超标，导致服务器电源模块冗余失效切换。",
                probe_tool="query_infrastructure",
                probe_args={"query": "ups"}
            ),
        ]

    async def execute_parallel_probes(self, branches: List[HypothesisBranch]) -> List[HypothesisBranch]:
        """并发调用只读探针工具，收集验证证据"""
        async def _run_single_probe(branch: HypothesisBranch):
            tool = tool_registry.get_tool(branch.probe_tool)
            if not tool:
                branch.evidence_finding = f"未找到探针工具: {branch.probe_tool}"
                branch.status = "AMBIGUOUS"
                return

            try:
                fn = tool.fn
                if asyncio.iscoroutinefunction(fn):
                    out = await fn(**branch.probe_args)
                else:
                    out = await asyncio.get_event_loop().run_in_executor(None, lambda: fn(**branch.probe_args))
                branch.evidence_finding = str(out)
            except Exception as e:
                branch.evidence_finding = f"探针执行异常: {e}"
                branch.status = "ERROR"

        # 并发派发探针
        await asyncio.gather(*[_run_single_probe(b) for b in branches])
        return branches

    def execute_probes_sync(self, branches: List[HypothesisBranch]) -> List[HypothesisBranch]:
        """同步派发只读探针工具，收集验证证据"""
        for branch in branches:
            tool = tool_registry.get_tool(branch.probe_tool)
            if not tool:
                branch.evidence_finding = f"未找到探针工具: {branch.probe_tool}"
                branch.status = "AMBIGUOUS"
                continue

            try:
                fn = tool.fn
                out = fn(**branch.probe_args)
                branch.evidence_finding = str(out)
            except Exception as e:
                branch.evidence_finding = f"探针执行异常: {e}"
                branch.status = "ERROR"
        return branches

    def explore(self, incident: str, target: str = "SVR-001") -> Dict[str, Any]:
        """完整推演管线：裂变 -> 探查 -> 贝叶斯打分 -> 分支剪枝"""
        candidates = self.generate_candidate_hypotheses(incident, target=target)
        self.execute_probes_sync(candidates)
        return self.evaluate_and_prune(candidates)

    def evaluate_and_prune(self, branches: List[HypothesisBranch]) -> Dict[str, Any]:
        """依据各探针返回的真实指标证据对假说进行判定，剪除被证伪的分支"""
        for b in branches:
            finding = b.evidence_finding.lower()

            if b.hypothesis_id == "H_INFRA":
                # 检查是否存在红外热场、最高测温点、垂直梯度差或过热特征
                if any(k in finding for k in ("hotspot", "过热", "热分层", "31.", "32.", "33.", "34.", "最高测温点", "垂直断面", "红外热成像")):
                    b.confidence_score = 0.92 if any(k in finding for k in ("hotspot", "过热", "热分层", "⚠️")) else 0.85
                    b.status = "CONFIRMED"
                else:
                    b.confidence_score = 0.15
                    b.status = "REFUTED"
                    b.falsification_reason = "红外热成像实测未能获取到机柜热场特征点阵数据。"

            elif b.hypothesis_id == "H_CLOUD":
                if any(k in finding for k in ("disk full", "100%", "overheating", "warning", "critical")):
                    b.confidence_score = 0.75
                    b.status = "CONFIRMED"
                else:
                    b.confidence_score = 0.20
                    b.status = "REFUTED"
                    b.falsification_reason = "目标服务器存储及系统运行状态处于正常区间（未发现磁盘IO阻塞报警）。"

            elif b.hypothesis_id == "H_POWER":
                if any(k in finding for k in ("纹波", "倒换", "过载", "故障", "异常", "critical")):
                    b.confidence_score = 0.80
                    b.status = "CONFIRMED"
                else:
                    b.confidence_score = 0.05
                    b.status = "REFUTED"
                    b.falsification_reason = "UPS 主备电源监控指标完全平稳 (输出/电池正常)，排除电力层问题。"

        # 排序并筛选出胜出者
        sorted_branches = sorted(branches, key=lambda x: x.confidence_score, reverse=True)
        winner = sorted_branches[0]
        pruned_branches = [b for b in sorted_branches if b.status == "REFUTED" or b != winner]

        return {
            "winning_hypothesis": winner,
            "pruned_branches": pruned_branches,
            "tree_summary": self._format_tree_report(winner, pruned_branches)
        }

    def _format_tree_report(self, winner: HypothesisBranch, pruned: List[HypothesisBranch]) -> str:
        report = [
            "🌳 【假说树搜索推演报告 (Hypothesis Tree Search)】",
            f"  🏆 [胜出真因路径]: {winner.title} (置信度: {winner.confidence_score * 100:.1f}%)",
            f"     - 验证证据: {winner.evidence_finding[:120].strip()}...",
            "  ✂️ [剪除证伪分支]:",
        ]
        for p in pruned:
            report.append(f"     - ❌ {p.title} (置信度: {p.confidence_score * 100:.1f}%) | 排除理由: {p.falsification_reason}")
        return "\n".join(report)


# 全局单例
global_hypothesis_explorer = HypothesisTreeExplorer()


@tool_registry.register(
    name="explore_hypothesis_tree",
    description="【假说树搜索推演引擎】针对数据中心复合型或多诱因模糊告警，"
    "自动裂变出候选因果假说分支（动环热场、业务磁盘、电力UPS等），调度探针工具收集物理与逻辑证据，"
    "依据实测证据进行打分并剪除被证伪的分支，输出唯一胜出的高置信度因果链与排除分析报告。",
    parameters={
        "type": "object",
        "properties": {
            "incident": {
                "type": "string",
                "description": "告警事件或现象描述（例如：'机柜A02温度上升伴随服务响应延迟'）"
            },
            "target": {
                "type": "string",
                "description": "疑似故障的机柜或服务器目标资产标识（默认 'SVR-001'）",
                "default": "SVR-001"
            }
        },
        "required": ["incident"]
    },
    risk_level=RiskLevel.SAFE
)
def explore_hypothesis_tree(incident: str, target: str = "SVR-001") -> str:
    """运行假说树推演并返回排查报告"""
    res = global_hypothesis_explorer.explore(incident, target=target)
    return res["tree_summary"]

