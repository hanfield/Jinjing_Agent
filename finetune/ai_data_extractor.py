import os
import json
import httpx
from dotenv import load_dotenv

# 确保能读取到项目根目录的 .env 中的 API_KEY
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
MODEL = os.getenv("LLM_MODEL", "Qwen/QwQ-32B")

SYSTEM_PROMPT = """
你是一个数据中心资深运维总监兼 AI 数据工程专家。
你的任务是阅读用户提供的非结构化运维事故报告、巡检日志或操作文档，提炼出其中有价值的运维经验、排查思路和处置结论，
并精准将其转化为高质量的【大模型微调问答样本】（Alpaca 格式）。

每条微调样本必须包含：
- instruction: 模拟运维人员可能提出的问题或触发的监控告警。
- input: 可留空字符串 ""。
- output: 具备严谨逻辑思维链（如：【风险评估】+【排查过程】+【处置步骤】）的专业解答，使用 markdown 格式排版。

请严格按 JSON 数组格式返回（不要有任何多余的寒暄，直接用 [ 开始用 ] 结束），例如：
[
  {
    "instruction": "静电地板下发现漏水告警，怎么处理？",
    "input": "",
    "output": "**【风险评估】** 严重短路风险... \\n**【处置流程】** 1. 切断电箱总闸..."
  }
]
"""

def extract_qa_from_report(report_text: str) -> list:
    """调用大模型，从非结构化文本中榨取 Q&A 数据"""
    if not API_KEY:
        print("❌ 未配置 OPENAI_API_KEY，无法调用大模型")
        return []

    print(f"🔄 正在调用大模型 ({MODEL}) 审阅分析报告，请稍候...")

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"请分析以下运维报告，提取所有的知识点并生成 JSON 数组格式的训练数据：\n\n{report_text}"}
        ],
        "temperature": 0.1  # 较低的温度，保证生成的结构更稳定
    }

    try:
        # 发起请求 (如果报告很长可能会需要一两分钟)
        with httpx.Client(timeout=180.0) as client:
            response = client.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()

        result = response.json()
        content = result["choices"][0]["message"]["content"].strip()

        # 简单清洗防漏：如果大模型自作主张加了 ```json 包装，将其剥离
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        data = json.loads(content.strip())
        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        return data if isinstance(data, list) else [data]

    except Exception as e:
        print(f"❌ 大模型解析失败或格式错误: {e}")
        try:
            print("模型原始返回内容截断预览:", content[:200])
        except Exception:
            pass
        return []

def main():
    # 设定输入与输出路径
    project_root = os.path.dirname(os.path.dirname(__file__))
    report_path = os.path.join(project_root, "data", "raw_report.txt")
    output_jsonl = os.path.join(project_root, "finetune", "train_data.jsonl")

    # 1. 检查有没有现成的报告，如果没有，自动建一个示范用的故障报告
    if not os.path.exists(report_path):
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("2025年3月12日，A区机房发生空调漏水事件复盘。\n")
            f.write("当时值班员发现静电地板下有积水告警，因为他先去关机器而不是先断下层电源，差点造成短路。\n")
            f.write("教训惨痛。正确做法应该是：一旦发生积水告警，第一步，必须立即切断该漏水区域地板下层配电箱的总闸，从物理上切断漏电起火隐患；")
            f.write("第二步，顺藤摸瓜查找上游的精密空调给水阀门或供水干管阀门并立刻将其彻底关闭；第三步，在确认电路无风险、漏水已阻断后，再去缓慢处理和抢救受潮的服务器等 IT 设备。")
        print(f"ℹ️ 未找到 {report_path} 文件。已自动为您生成一份【测试漏水事故复盘报告】用作演示。")

    # 2. 读取非结构化原始文档
    with open(report_path, "r", encoding="utf-8") as f:
        report_text = f.read()

    # 3. 呼叫大模型干活，从中“提取知识金矿”
    qa_list = extract_qa_from_report(report_text)

    # 4. 把大模型生成的纯净数据，追加写入我们的微调训练集
    if qa_list:
        with open(output_jsonl, "a", encoding="utf-8") as f:
            for qa in qa_list:
                f.write(json.dumps(qa, ensure_ascii=False) + "\n")

        print(f"\n✅ 成功！大模型从一篇生涩的报告中提纯了 {len(qa_list)} 条精炼的处置方案。")
        print(f"📁 数据已自动追加到微调文件: {output_jsonl}")
        print("\n--- 提取成果速览 ---")
        for i, qa in enumerate(qa_list, 1):
             q = str(qa.get('instruction'))
             a = str(qa.get('output'))
             print(f"[{i}] 触发问: {q[:40]}...")
             print(f"    神回复: {a[:50]}...")
    else:
        print("⚠️ 未提取到任何有效数据，可能是受限报告内容，或者大模型未能按格式返回。")

if __name__ == "__main__":
    main()
