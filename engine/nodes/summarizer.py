"""
金枢 3.0 - L1 汇总节点 (Summarizer Node)
========================================
替代原：
  engine/multi_agent/supervisor.py :: SupervisorAgent.synthesize_summary()

在 LangGraph 图的最后阶段执行。读取 JinShuState 中的 evidence_chain 等
黑板数据，调用 LLM 生成最终的给运维总监的结构化排障报告。
报告生成后，发布 final_chunk 事件供前端渲染。
"""

import json
import os
import httpx

from engine.core.state import JinShuState

# ── LLM 配置（遵循 AGENTS.md 规范） ───────────────────────────────
_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
_MODEL = os.getenv("LLM_MODEL", "Qwen/QwQ-32B")


async def summarizer_node(state: JinShuState) -> dict:
    """
    汇聚专家推演结论，生成高管汇报。
    """
    user_message = state["user_message"]
    
    # 构造类似于原 Blackboard 导出的快照
    blackboard_snapshot = {
        "status": state.get("overall_status", "NORMAL"),
        "environment_status": state.get("environment_status", {}),
        "affected_hosts": state.get("affected_hosts", []),
        "security_locks": state.get("security_locks", {}),
        "evidence_count": len(state.get("evidence_chain", [])),
        "evidence_chain": state.get("evidence_chain", []),
        "approval_pending": state.get("pending_approval") is not None
    }

    prompt = f"""你是金枢 3.0 L1 总指挥。请根据以下黑板总线中的专家推演结论，生成一份最终给运维总监的结构化排障报告。
要求包含：【态势感知】、【各专家处置结论】、【风险判定证据链】。

原始用户提问/告警：{user_message}

黑板快照：
{json.dumps(blackboard_snapshot, ensure_ascii=False, indent=2)}
"""

    events = []
    events.append({"event": "start_thinking", "expert": "L1_Supervisor"})
    
    try:
        payload = {
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "请生成最终汇总报告"}
            ],
            "temperature": 0.1
        }
        
        async with httpx.AsyncClient(timeout=45.0) as client:
            headers = {"Authorization": f"Bearer {_API_KEY}"} if _API_KEY else {}
            resp = await client.post(f"{_BASE_URL}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            summary = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        summary = f"汇总报告生成失败: {e}"

    import re
    thought_match = re.search(r"<think>([\s\S]*?)</think>", summary)
    if thought_match:
        thought_text = thought_match.group(1).strip()
        events.append({"event": "thought", "expert": "L1_Supervisor", "text": thought_text})
        clean_summary = re.sub(r"<think>[\s\S]*?</think>", "", summary).strip()
    else:
        clean_summary = summary

    events.append({"event": "final_chunk", "expert": "L1_Supervisor", "text": f"\n\n{clean_summary}"})

    return {
        "final_summary": clean_summary,
        "stream_events": events
    }

