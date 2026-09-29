"""
金枢 (Jin-Shu) - 专家大白话转 Qwen2.5 格式工具
================================================
读取 data/expert_input.md 中的大白话极简案例，
通过大模型“膨胀”成符合 Qwen2.5 工具调用规范的 JSONL 会话数据。
"""

import os
import json
import asyncio
from dotenv import load_dotenv
import httpx

load_dotenv()

PROMPT_TEMPLATE = """
你是一个底层数据清洗引擎。你的任务是把运维专家的“大白话”检修记录，转化为一次完美的智能 Agent 对话流程。
目标格式必须严格遵守 Qwen2.5 的 Function Calling 格式。

【专家大白话记录】：
{case_text}

【你需要调用的工具列表】：
1. query_infrastructure(query: str) - 查询设施，如查询"A区"或"HVAC"
2. resolve_spatial_topology(asset_id: str, dc_id: str) - 空间拓扑溯源

【生成要求】：
请生成一段 JSON，模拟真实人机对话，包含完整的工具调用过程。
必须输出合法的 JSON 格式，不要包裹在 Markdown 代码块中！不要输出其他说明文字。
JSON 的格式如下：
{{
  "messages": [
    {{
      "role": "system",
      "content": "你是金枢智能运维 Agent..."
    }},
    {{
      "role": "user",
      "content": "用户提出的问题（根据案例改编）"
    }},
    {{
      "role": "assistant",
      "content": "思考过程（如果不调用工具则为空）",
      "tool_calls": [
        {{
          "type": "function",
          "function": {{
            "name": "这里写工具名",
            "arguments": "{{\"参数名\": \"参数值\"}}"
          }}
        }}
      ]
    }},
    {{
      "role": "tool",
      "name": "这里写工具名",
      "content": "模拟工具返回的排查结果"
    }},
    {{
      "role": "assistant",
      "content": "根据工具返回的结果，给出的最终专家建议"
    }}
  ]
}}
"""

async def call_llm_to_inflate(case_text: str) -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
    model = os.getenv("LLM_MODEL", "deepseek-chat")

    prompt = PROMPT_TEMPLATE.format(case_text=case_text)
    
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2
                }
            )
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            # 尝试清理 markdown 代码块
            content = content.replace("```json\n", "").replace("```", "").strip()
            return json.loads(content)
        except Exception as e:
            print(f"❌ LLM 膨胀失败：{e}")
            return None

async def main():
    input_file = "data/expert_input.md"
    output_file = "finetune/qwen_train.jsonl"
    
    if not os.path.exists(input_file):
        print(f"❌ 找不到输入文件：{input_file}")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        content = f.read()

    # 按【案例XXX】切分
    cases = [c.strip() for c in content.split("【案例") if c.strip()]
    
    print(f"🔍 找到了 {len(cases)} 个专家大白话案例，开始清洗和膨胀...")
    
    out_f = open(output_file, "w", encoding="utf-8")
    success_count = 0

    for i, case in enumerate(cases):
        case_idx = case.split("】")[0]
        case_body = case.split("】")[1].strip() if "】" in case else case
        print(f"⏳ 正在处理案例 {case_idx}...")
        
        result_json = await call_llm_to_inflate(case_body)
        if result_json:
            out_f.write(json.dumps(result_json, ensure_ascii=False) + "\n")
            success_count += 1
            print(f"✅ 案例 {case_idx} 转换成功！")
        else:
            print(f"❌ 案例 {case_idx} 转换失败。")

    out_f.close()
    print("=" * 50)
    print(f"🎉 转换完成！成功生成 {success_count} 条 Qwen2.5 训练数据。")
    print(f"👉 训练数据保存在：{output_file}")
    print("现在你可以直接把 qwen_train.jsonl 喂给 ms-swift 或者 LLaMA-Factory 进行微调了！")

if __name__ == "__main__":
    asyncio.run(main())
