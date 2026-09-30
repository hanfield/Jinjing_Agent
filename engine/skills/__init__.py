"""
金枢 3.0 (Jin-Shu OS) - 高阶复合技能模块导出
=============================================
集中导出高阶运维与安全治理技能，并在全局 SkillRegistry 中完成注册。
"""

from engine.skills.base import (
    BaseSkill,
    SkillStatus,
    SkillExecutionResult,
    SkillRegistry,
    global_skill_registry,
)
from engine.skills.thermal_remediation_skill import (
    ThermalAnomalyRemediationSkill,
    thermal_remediation_skill,
)
from engine.skills.blast_radius_safety_skill import (
    SafeRemediationBlastRadiusSkill,
    blast_radius_safety_skill,
)
from engine.skills.incident_postmortem_skill import (
    IncidentPostMortemSynthesisSkill,
    incident_postmortem_skill,
)

# 统一向全局中枢完成技能注册
global_skill_registry.register(thermal_remediation_skill)
global_skill_registry.register(blast_radius_safety_skill)
global_skill_registry.register(incident_postmortem_skill)

__all__ = [
    "BaseSkill",
    "SkillStatus",
    "SkillExecutionResult",
    "SkillRegistry",
    "global_skill_registry",
    "ThermalAnomalyRemediationSkill",
    "thermal_remediation_skill",
    "SafeRemediationBlastRadiusSkill",
    "blast_radius_safety_skill",
    "IncidentPostMortemSynthesisSkill",
    "incident_postmortem_skill",
]
