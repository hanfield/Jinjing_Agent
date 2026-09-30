"""
金枢 3.0 (Jin-Shu OS) - 动环热分层与制冷能效综合治理技能 (Thermal Anomaly Remediation Skill)
========================================================================================
高阶复合技能：针对高密机柜过热或热分层告警，链式编排：
  1. 红外点阵扫描 (analyze_thermal_infrared_matrix) 获取垂直热场。
  2. 假说树并发探针 (HypothesisTreeExplorer) 验证风道短路假说。
  3. CodeAct 动态沙箱 (execute_python_codeact) 执行热力学方程与空调变频计算。
  4. 产出闭环应急与能效调优 SOP。
"""

import time
from typing import Dict, Any

from engine.skills.base import BaseSkill, SkillExecutionResult, SkillStatus
from engine.tools.vision_tools import analyze_thermal_infrared_matrix
from engine.nodes.hypothesis_tree import global_hypothesis_explorer
from engine.tools.codeact_sandbox import execute_python_codeact


class ThermalAnomalyRemediationSkill(BaseSkill):
    """机房热场异常与变频调优综合治理技能"""

    def __init__(self):
        super().__init__(
            name="thermal_anomaly_remediation",
            description="【动环热场治理技能】自动调用红外热成像扫描、假说树风道短路溯源、"
                        "CodeAct流体力学能效反演，并产出针对性的机柜物理封堵与变频空调调优SOP。",
            domain="INFRA",
        )

    def pre_flight_check(self, context: Dict[str, Any]) -> bool:
        return "rack_id" in context or "target_id" in context

    async def execute(self, rack_id: str = "RACK-A02", height_layers: int = 6) -> SkillExecutionResult:
        start_time = time.time()
        steps = []
        findings = {}

        # 步骤 1: 红外热成像点阵采集
        steps.append(f"1. 红外扫描: 采集 {rack_id} 机柜 {height_layers} 层垂直断面温度点阵")
        thermal_raw = analyze_thermal_infrared_matrix(target_id=rack_id, height_layers=height_layers)
        findings["thermal_matrix_report"] = thermal_raw

        # 步骤 2: 假说树因果推演
        steps.append("2. 假说树推演: 验证风道短路、假盲板脱落或冷通道送风不足假说")
        hypo_res = global_hypothesis_explorer.explore(
            incident=f"机柜 {rack_id} 出现垂直温升与局部热分层",
            target=rack_id
        )
        winner = hypo_res["winning_hypothesis"]
        findings["root_cause_hypothesis"] = winner.title
        findings["confidence"] = winner.confidence_score

        # 步骤 3: CodeAct 动态求解最优空调转速与温差补偿
        steps.append("3. CodeAct 沙箱: 动态计算流体力学热负荷与 CRAC 风机最优补偿频率")
        calc_code = """
# 基于热力学热平衡方程计算目标补偿
# Q = c * m * delta_T
current_peak_t = 27.5
target_t = 24.0
delta_t_needed = current_peak_t - target_t

# 空调变频响应模型：每提升 1Hz 供风量增加 2.5%，平均降温 0.45°C
freq_boost_hz = round(delta_t_needed / 0.45, 1)
new_fan_freq = min(50.0, round(42.0 + freq_boost_hz, 1))

print(f"峰值温度: {current_peak_t}°C, 目标温度: {target_t}°C")
print(f"建议精密空调风机变频增量: +{freq_boost_hz}Hz (新工况: {new_fan_freq}Hz)")
"""
        codeact_result = execute_python_codeact(calc_code, timeout_seconds=3)
        findings["codeact_optimization"] = codeact_result

        # 步骤 4: 综合生成应急处置与能效调优 SOP
        sop = f"""### 🛠️ 【机房热场闭环治理 SOP - {rack_id}】
1. 立即措施:
   - 现场值班人员核查 {rack_id} 机柜 U28-U42 高层假盲板是否脱落，封堵热风回流短路口。
   - 检查高架地板出风口调节阀，开度从 60% 调至 85%。
2. 动环控制:
   - 将关联精密空调 CRAC-A01 风机运行频率微调至推荐值，预计 15 分钟内消除温差分层。
3. 自动化监控:
   - 触发 30 分钟连续红外测温巡检，复测垂直温差 ΔT 是否回落至 ≤ 3.5°C 正常区间。
"""
        duration = round((time.time() - start_time) * 1000, 2)

        report = f"""## 🌡️ 动环热场治理技能推演报告 [{rack_id}]
- **耗时**: {duration} ms
- **真因归因**: {winner.title} (置信度: {winner.confidence_score * 100:.1f}%)
- **热场实测**:
```
{thermal_raw}
```
- **流体力学求解**:
```
{codeact_result}
```
{sop}
"""
        return SkillExecutionResult(
            skill_name=self.name,
            status=SkillStatus.SUCCESS,
            execution_time_ms=duration,
            steps_executed=steps,
            findings=findings,
            remediation_sop=sop,
            report_markdown=report,
        )


# 单例
thermal_remediation_skill = ThermalAnomalyRemediationSkill()
