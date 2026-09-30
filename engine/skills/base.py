"""
金枢 3.0 (Jin-Shu OS) - 高阶复合技能基类与注册中枢 (Agent Skill Architecture)
=============================================================================
在 Agent 架构中，Tool 是原子的单步操作，而 Skill 是封装了业务 SOP、状态校验、
多工具链式编排与前置后置防御的高阶复合能力。

核心设计：
  1. BaseSkill: 规范 pre_flight_check -> execute -> post_execution_verify 标准三段式生命周期。
  2. SkillExecutionResult: 标准化技能产物，包含执行状态、执行步骤、因果证据与推荐 SOP。
  3. SkillRegistry: 统一管理专家技能，并可自动向原子工具注册表暴露为高阶工具。
"""

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional


class SkillStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


@dataclass
class SkillExecutionResult:
    """技能执行结果"""
    skill_name: str
    status: SkillStatus
    execution_time_ms: float
    steps_executed: List[str] = field(default_factory=list)
    findings: Dict[str, Any] = field(default_factory=dict)
    remediation_sop: str = ""
    report_markdown: str = ""
    error_message: Optional[str] = None


class BaseSkill(abc.ABC):
    """高阶技能抽象基类"""

    def __init__(self, name: str, description: str, domain: str):
        self.name = name
        self.description = description
        self.domain = domain  # "INFRA", "CLOUD", "SECURITY", "SRE"

    @abc.abstractmethod
    def pre_flight_check(self, context: Dict[str, Any]) -> bool:
        """前置安全性与参数校验"""
        pass

    @abc.abstractmethod
    async def execute(self, **kwargs) -> SkillExecutionResult:
        """执行复合技能编排"""
        pass


class SkillRegistry:
    """复合技能注册中枢"""

    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill):
        self._skills[skill.name] = skill
        return skill

    def get_skill(self, name: str) -> Optional[BaseSkill]:
        return self._skills.get(name)

    def list_skills(self) -> List[Dict[str, str]]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "domain": s.domain,
            }
            for s in self._skills.values()
        ]


# 全局单例
global_skill_registry = SkillRegistry()
