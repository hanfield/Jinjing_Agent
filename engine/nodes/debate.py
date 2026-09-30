"""
金枢 3.0 (Jin-Shu OS) - 多智能体学术辩论与共识达成节点 (Multi-Agent Debate & Consensus)
======================================================================================
解决数据中心运维中最典型的【多目标利益冲突】：
  - 动环专家 (L2_Infra)：追求最低 PUE、抑制物理热失控、降低能耗。
  - 云原生专家 (L2_Cloud)：追求业务 99.999% SLA 可用性、避免交易超时与计算降频。

当两类专家对同一机房区域提出处置建议时，系统自动拉起【辩论与协商网关】。
通过结构化多轮辩论与帕累托最优推演，输出兼顾物理安全与金融 SLA 的共识执行方案。
"""

import os
import json
import re
import httpx
from typing import Dict, Any, List

from engine.core.state import JinShuState

_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
_MODEL = os.getenv("LLM_MODEL", "Qwen/QwQ-32B")


def should_enter_debate(state: JinShuState) -> bool:
    """
    判断是否需要触发多智能体辩论：
    条件：动环专家 (L2_Infra) 与云原生专家 (L2_Cloud) 同时介入并各自产出了风险研判
    """
    ev_agents = {ev["source_agent"] for ev in state.get("evidence_chain", [])}
    return ("L2_Infra" in ev_agents and "L2_Cloud" in ev_agents)


async def debate_consensus_node(state: JinShuState) -> dict:
    """
    辩论与共识求解节点：
    驱动 Infra 与 Cloud 专家的冲突对抗与对齐，求解帕累托最优平衡。
    """
    events = []
    events.append({
        "event": "start_thinking",
        "expert": "Consensus_Engine",
        "text": "检测到【物理动环能耗】与【云端业务SLA】潜在多目标冲突，正在拉起专委会辩论..."
    })

    user_message = state["user_message"]
    evidence_chain = state.get("evidence_chain", [])
    infra_evidence = [e for e in evidence_chain if e["source_agent"] == "L2_Infra"]
    cloud_evidence = [e for e in evidence_chain if e["source_agent"] == "L2_Cloud"]

    debate_prompt = f"""你是金枢多智能体冲突协商中枢 (Consensus Arbiter)。
现在数据中心发生了以下运维事件：
【用户告警/事件】：{user_message}

【动环专家 (L2_Infra) 判定】：
{json.dumps(infra_evidence, ensure_ascii=False, indent=2)}

【云原生专家 (L2_Cloud) 判定】：
{json.dumps(cloud_evidence, ensure_ascii=False, indent=2)}

请模拟 L2_Infra 与 L2_Cloud 两名专家的 1 轮对抗性辩论，并由你给出最终的【帕累托最优共识方案】：
1. [L2_Infra 辩词]：阐述物理散热极限与电力热衰竭风险，提出调控要求。
2. [L2_Cloud 辩词]：阐述金融交易 SLA 连续性与业务洪峰压力，反驳粗暴限流关机。
3. [共识方案 (Consensus)]：给出协同处置的具体步骤（例如：先热迁移非核心虚机，再平滑调节冷通道送风）。

请严格按以下 JSON 格式返回：
{{
  "infra_stance": "动环专家的辩词...",
  "cloud_stance": "云原生专家的抗辩...",
  "consensus_solution": "帕累托最优的联合处置步骤..."
}}
"""

    consensus_solution = ""
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            headers = {"Authorization": f"Bearer {_API_KEY}"} if _API_KEY else {}
            resp = await client.post(
                f"{_BASE_URL}/chat/completions",
                headers=headers,
                json={
                    "model": _MODEL,
                    "messages": [
                        {"role": "system", "content": "你是严谨的金融级数据中心冲突协商裁决引擎。"},
                        {"role": "user", "content": debate_prompt}
                    ],
                    "temperature": 0.2
                }
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            
            # 清理思维链标签
            content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
            if content.startswith("```json"): content = content[7:]
            if content.startswith("```"): content = content[3:]
            if content.endswith("```"): content = content[:-3]
            
            parsed = json.loads(content.strip())
            
            # 发射辩论流式事件，供前端渲染实时对抗
            events.append({
                "event": "debate_turn",
                "expert": "L2_Infra",
                "text": f"🗣️ [动环专家主张]: {parsed.get('infra_stance', '')}"
            })
            events.append({
                "event": "debate_turn",
                "expert": "L2_Cloud",
                "text": f"🛡️ [云原生专家抗辩]: {parsed.get('cloud_stance', '')}"
            })
            events.append({
                "event": "consensus_reached",
                "expert": "Consensus_Engine",
                "text": f"🤝 [专委会达成共识方案]: {parsed.get('consensus_solution', '')}"
            })
            
            consensus_solution = parsed.get("consensus_solution", "")
            
    except Exception as e:
        consensus_solution = f"多专家自动协商降级：优先保障生产连续性与 SLA，协同微调动环策略 ({e})"
        events.append({
            "event": "consensus_reached",
            "expert": "Consensus_Engine",
            "text": f"🤝 [共识降级模式]: {consensus_solution}"
        })

    return {
        "final_summary": f"### ⚖️ 多智能体协商共识方案\n{consensus_solution}",
        "stream_events": events
    }
