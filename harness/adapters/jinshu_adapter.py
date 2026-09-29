"""
金枢 2.0 (Jin-Shu OS) - JinShu Agent Adapter (金枢专属驱动适配器)
==================================================================
将金枢自研的 Multi-Agent 星型总线引擎无缝对接到标准 Harness 评测底架中。
提取细粒度的 Span Traces，驱动企业级沙箱 API。
"""

import time
from typing import Dict, Any
from harness.tasks.task_registry import BenchmarkTask
from harness.environments.sandbox_proxy import SandboxProxyHarness
from harness.adapters.base_adapter import BaseAgentAdapter

from engine.core import multi_agent_orchestrator


class JinShuAgentAdapter(BaseAgentAdapter):
    """金枢专属驱动适配层"""

    async def run_task(self, task: BenchmarkTask) -> Dict[str, Any]:
        """驱动 Agent 执行任务并捕获遥测指标"""
        # 使用水合后的真实数据初始化沙箱
        state = task.hydrate_state()
        self.sandbox.setup_sandbox(state, task.chaos_config)
        
        start_time = time.time()
        first_token_time = None
        full_response = []
        executed_tools = []
        invoked_experts = set()
        approval_triggered = False
        
        # 记录 Span Traces
        span_traces = []

        # 驱动金枢并发多智能体引擎推演
        async for event in multi_agent_orchestrator.run_orchestration_stream(task.user_prompt):
            if not first_token_time and event.get("event") in ["start_thinking", "thought", "final_chunk"]:
                first_token_time = time.time()

            expert = event.get("expert")
            if expert:
                invoked_experts.add(expert)

            if event.get("event") == "tool_call":
                tool_name = event.get("name")
                executed_tools.append(tool_name)
                args = event.get("args", {})
                
                # 企业级沙箱：拦截并模拟执行
                await self.sandbox.execute_simulated_api(expert or "system", tool_name, args)
                
            elif event.get("event") == "approval_required":
                approval_triggered = True
            elif event.get("event") == "final_chunk":
                full_response.append(event.get("text", ""))

        elapsed_ms = (time.time() - start_time) * 1000.0
        ttft_ms = (first_token_time - start_time) * 1000.0 if first_token_time else elapsed_ms
        
        # 从沙箱拉取拦截到的工具调用，作为 span_traces 返回
        for call in self.sandbox.intercepted_tool_calls:
            span_traces.append({
                "agent_id": call["agent_id"],
                "tool_name": call["tool_name"],
                "args": call["args"],
                "timestamp": call["timestamp"]
            })

        return {
            "final_solution": "".join(full_response),
            "executed_tools": executed_tools,
            "invoked_experts": list(invoked_experts),
            "approval_triggered": approval_triggered,
            "execution_latency_ms": elapsed_ms,
            "ttft_ms": ttft_ms,
            "estimated_tokens": len("".join(full_response)) * 2 + 500,
            "span_traces": span_traces
        }
