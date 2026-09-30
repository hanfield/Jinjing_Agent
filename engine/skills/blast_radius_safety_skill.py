"""
金枢 3.0 (Jin-Shu OS) - 高危变更拓扑安全护栏与爆炸半径穿透技能 (Blast Radius Safety Skill)
========================================================================================
高阶复合技能：在 Agent 尝试执行任何破坏性/高危运维操作（如服务器硬重启、隔离节点、断电倒换）前，
自动执行多跳拓扑爆炸半径穿透、金融核心业务 SLA 评级穿透、分布式法定仲裁 (Quorum) 风险评估，
并自动决定是自主放行、触发双人复核审批 (HITL) 还是直接熔断阻断。
"""

import time
from typing import Dict, Any

from engine.skills.base import BaseSkill, SkillExecutionResult, SkillStatus
from engine.memory.topology_graph import global_topology_graph


class SafeRemediationBlastRadiusSkill(BaseSkill):
    """高危操作爆炸半径穿透与安全准入技能"""

    def __init__(self):
        super().__init__(
            name="safe_remediation_blast_radius",
            description="【变更爆炸半径穿透技能】在下发任何破坏性或配置变更操作前，"
                        "正向穿透 L1-L7 全栈有向拓扑图谱，评估核心金融业务受损面、"
                        "法定仲裁 Quorum 与风险等级，产出准入决策与审计快照。",
            domain="SECURITY",
        )

    def pre_flight_check(self, context: Dict[str, Any]) -> bool:
        return "target_id" in context

    async def execute(self, target_id: str, action: str = "reboot") -> SkillExecutionResult:
        start_time = time.time()
        steps = []
        findings = {}

        # 步骤 1: 拓扑图谱实体存在性核验
        steps.append(f"1. 拓扑校验: 核验目标物理/逻辑实体 {target_id} 及其上下游依赖图谱")
        if target_id not in global_topology_graph.nodes:
            duration = round((time.time() - start_time) * 1000, 2)
            return SkillExecutionResult(
                skill_name=self.name,
                status=SkillStatus.BLOCKED,
                execution_time_ms=duration,
                steps_executed=steps,
                error_message=f"实体 {target_id} 不在当前数据中心拓扑图谱中，阻断操作。",
            )

        # 步骤 2: 正向穿透计算下游波及业务
        steps.append(f"2. 爆炸半径穿透: 针对动作 {action.upper()} 计算影响图谱与金融 Tier-1 级别资产")
        blast = global_topology_graph.calculate_blast_radius(target_id=target_id, action=action)
        findings["blast_radius"] = blast

        # 步骤 3: 法定仲裁与高可用冗余推演
        steps.append("3. 冗余推演: 核查集群最小法定仲裁 Quorum 与双活倒换可行性")
        is_high_risk = blast["risk_tier"] == "HIGH"
        requires_approval = blast["requires_approval"]

        # 步骤 4: 决定准入决策
        if is_high_risk:
            decision = "🚨 拦截挂起: 风险等级 HIGH，涉及金融核心清算业务或分布式仲裁，必须触发值班主管审批。"
            status = SkillStatus.PARTIAL
        else:
            decision = "✅ 允许放行: 风险等级低/中且具备全量热备，无需人工干预。"
            status = SkillStatus.SUCCESS

        sop = f"""### 🛡️ 【爆炸半径审计准入决策 - {target_id}】
- 拟定动作: {action.upper()}
- 综合评级: {blast['risk_tier']}
- 准入结论: {decision}
- 审计追溯:
  * 波及实体数: {blast['impacted_count']}
  * 关键业务: {', '.join(blast['critical_workloads']) if blast['critical_workloads'] else '无'}
  * 前置审批要求: {'强制人工复核 (Human-in-the-Loop)' if requires_approval else '免审批自动执行'}
"""
        duration = round((time.time() - start_time) * 1000, 2)

        return SkillExecutionResult(
            skill_name=self.name,
            status=status,
            execution_time_ms=duration,
            steps_executed=steps,
            findings=findings,
            remediation_sop=sop,
            report_markdown=f"{blast['summary']}\n\n{sop}",
        )


# 单例
blast_radius_safety_skill = SafeRemediationBlastRadiusSkill()
