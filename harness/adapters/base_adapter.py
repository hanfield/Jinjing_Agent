"""
金枢 2.0 (Jin-Shu OS) - Base Agent Adapter (标准化智能体驱动基类)
================================================================
隔离具体智能体运行时框架 (金枢/LangChain/AutoGen/OpenAI)，定义统一的驱动生命周期接口。
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
from harness.tasks.task_registry import BenchmarkTask
from harness.environments.sandbox_proxy import SandboxProxyHarness


class BaseAgentAdapter(ABC):
    """标准化驱动适配器基类"""

    def __init__(self, sandbox: SandboxProxyHarness):
        self.sandbox = sandbox

    @abstractmethod
    async def run_task(self, task: BenchmarkTask) -> Dict[str, Any]:
        """
        驱动底层智能体执行基准任务。
        必须返回包含以下标准字段的字典：
        - final_solution: 最终输出文本
        - executed_tools: 执行的工具名称列表
        - invoked_experts: 调度的专家代号列表
        - approval_triggered: 是否触发高危拦截
        - execution_latency_ms: 执行总时延
        - ttft_ms: 首字时延
        """
        pass
