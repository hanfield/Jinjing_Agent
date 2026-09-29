"""
金枢 3.0 - Supervisor 节点 (Python 3.9 兼容版)
=================================================
替代原：engine/multi_agent/supervisor.py :: SupervisorAgent
"""

import json
import os
from typing import Literal, List, Dict

import httpx

from engine.core.state import JinShuState

# ── LLM 配置 ─────────────────────────────────────────────────────────
_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
_MODEL = os.getenv("LLM_MODEL", "Qwen/QwQ-32B")

_SUPERVISOR_SYSTEM_PROMPT = """你是金枢 3.0 L1 路由分诊台 (Supervisor Agent)。
你的唯一职责是阅读告警或用户提问，分析需要调度哪些 L2 领域专家介入。

可选专家列表：
- L2_Infra: 动环与基础设施专家（负责机温、UPS、空调、电力、动态基线）
- L2_Cloud: 云原生与系统专家（负责服务器实例、磁盘清理、进程异常、OpenStack/K8s）
- L2_Sec: 安防与合规专家（负责门禁出入、高危操作拦截流、配电锁）

请只返回一个 JSON 数组，包含需要调度的专家代号，例如 ["L2_Infra", "L2_Cloud"]。
不要有任何其他解释。"""


def _fallback_triage(user_message: str) -> List[str]:
    """
    关键词降级路由策略。
    """
    experts: set[str] = set()
    if any(k in user_message for k in ["温度", "空调", "UPS", "电源", "基线", "制冷", "A区", "动环", "机柜"]):
        experts.add("L2_Infra")
    if any(k in user_message for k in ["服务器", "磁盘", "进程", "虚拟机", "重启", "执行", "du ", "df ", "SVR", "容器", "K8s"]):
        experts.add("L2_Cloud")
    if any(k in user_message for k in ["门禁", "外部人员", "安防", "审批", "权限", "巡检"]):
        experts.add("L2_Sec")
    return list(experts) if experts else ["L2_Infra", "L2_Cloud"]


async def supervisor_node(state: JinShuState) -> dict:
    """
    Supervisor 节点：LLM 驱动的任务拆解与路由分诊。
    """
    user_message = state["user_message"]
    experts: List[str] = []

    # 通知前端：Supervisor 开始思考
    thinking_event = {"event": "start_thinking", "expert": "L1_Supervisor"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {"Authorization": f"Bearer {_API_KEY}"} if _API_KEY else {}
            resp = await client.post(
                f"{_BASE_URL}/chat/completions",
                headers=headers,
                json={
                    "model": _MODEL,
                    "messages": [
                        {"role": "system", "content": _SUPERVISOR_SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": 0.0,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

            # 清理 <think>...</think> 推理模型的思维链包裹
            import re
            cleaned_content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()

            # 清理 markdown 代码块包裹
            for prefix in ("```json", "```"):
                if cleaned_content.startswith(prefix):
                    cleaned_content = cleaned_content[len(prefix):]
            if cleaned_content.endswith("```"):
                cleaned_content = cleaned_content[:-3]

            # 尝试正向解析或正则提取 JSON 数组
            cleaned_content = cleaned_content.strip()
            try:
                parsed = json.loads(cleaned_content)
            except Exception:
                match = re.search(r"\[[\s\S]*?\]", cleaned_content)
                parsed = json.loads(match.group(0)) if match else None

            if isinstance(parsed, list) and all(isinstance(e, str) for e in parsed):
                experts = parsed


    except Exception as exc:
        print(f"[Supervisor] LLM 分诊异常，启用降级路由: {exc}")
        experts = _fallback_triage(user_message)

    if not experts:
        experts = _fallback_triage(user_message)

    triage_event = {
        "event": "triage_decision",
        "experts": experts,
        "expert": "L1_Supervisor",
    }

    return {
        "experts_to_invoke": experts,
        "experts_completed": [],
        "stream_events": [thinking_event, triage_event],
    }


# ── 条件路由函数（图的边逻辑）────────────────────────────────────────

def route_to_workers(
    state: JinShuState,
) -> List[Literal["infra_worker", "cloud_worker", "sec_worker", "summarizer"]]:
    """
    Fan-out 路由：根据 experts_to_invoke 并发分发到各 Worker 节点。
    """
    expert_to_node: Dict[str, str] = {
        "L2_Infra": "infra_worker",
        "L2_Cloud": "cloud_worker",
        "L2_Sec": "sec_worker",
    }
    experts = state.get("experts_to_invoke", [])
    targets = [expert_to_node[e] for e in experts if e in expert_to_node]
    return targets if targets else ["summarizer"]
