"""
金枢 (Jin-Shu) - SFT 微调数据准备脚本
================================================
将原始运维文档（Markdown/TXT/JSON 工单）转换为
大模型微调所需的标准 JSONL 格式训练数据。

输出格式（Alpaca 风格，业界最通用）：
{
    "instruction": "用户的问题或指令",
    "input": "附加上下文（可选）",
    "output": "期望模型生成的标准回答（含思维链）"
}

使用方法：
    python -m finetune.prepare_data
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass, asdict


@dataclass
class TrainingSample:
    """一条微调训练样本"""
    instruction: str   # 用户问题
    input: str = ""    # 附加上下文
    output: str = ""   # 标准回答


class DataPreparer:
    """
    微调数据准备器。
    负责从不同来源提取、转换并输出标准格式的训练数据。
    """

    def __init__(self, output_path: str = "finetune/train_data.jsonl"):
        self.samples: list[TrainingSample] = []
        self.output_path = Path(output_path)

    def add_sample(self, instruction: str, output: str, input_ctx: str = ""):
        """手动添加一条训练样本"""
        self.samples.append(TrainingSample(
            instruction=instruction,
            input=input_ctx,
            output=output,
        ))

    def load_from_sop_markdown(self, md_path: str):
        """
        从 SOP 手册 Markdown 中自动提取 Q&A 对。
        每个 ## 标题对应一个 SOP，自动生成问答。
        """
        path = Path(md_path)
        if not path.exists():
            print(f"⚠️ 文件不存在: {md_path}")
            return

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        sections = content.split("\n## ")
        for section in sections:
            if not section.strip():
                continue

            lines = section.strip().split("\n")
            title = lines[0].strip("# ").strip()
            body = "\n".join(lines[1:]).strip()

            if not title or not body:
                continue

            # 提取 SOP 编号（如果有）
            sop_match = re.search(r"(SOP-\w+-\d+)", title)
            sop_id = sop_match.group(1) if sop_match else ""

            # 自动生成多种问法
            questions = [
                f"{title.split('（')[0]}应该怎么处理？",
                f"请提供{title.split('（')[0]}的标准操作流程。",
            ]
            if sop_id:
                questions.append(f"请查询 {sop_id} 的处置步骤。")

            # 构造含思维链的标准回答
            cot_answer = (
                f"**【问题识别】** 用户询问的是关于「{title}」的处置规范。\n"
                f"**【知识检索】** 已从专家知识库中定位到相关 SOP 文档。\n"
                f"**【标准答案】**\n\n{body}"
            )

            for q in questions:
                self.add_sample(instruction=q, output=cot_answer)

        print(f"✅ 从 SOP 手册提取了 {len(self.samples)} 条训练样本。")

    def load_from_tickets_json(self, json_path: str):
        """
        从故障工单 JSON 文件中提取训练数据。
        每条工单应包含：alarm（告警）、process（处理过程）、conclusion（结论）。
        """
        path = Path(json_path)
        if not path.exists():
            print(f"⚠️ 文件不存在: {json_path}")
            return

        with open(path, "r", encoding="utf-8") as f:
            tickets = json.load(f)

        for ticket in tickets:
            alarm = ticket.get("alarm", "")
            process = ticket.get("process", "")
            conclusion = ticket.get("conclusion", "")

            if not alarm or not process:
                continue

            instruction = f"收到告警：{alarm}。请分析原因并给出处置建议。"
            output = (
                f"**【告警分析】** {alarm}\n"
                f"**【排查过程】** {process}\n"
                f"**【最终结论】** {conclusion}"
            )

            self.add_sample(instruction=instruction, output=output)

        print(f"✅ 从故障工单提取了 {len(tickets)} 条训练样本。")

    def generate_tool_calling_samples(self):
        """
        生成 Agent 工具调用相关的训练样本。
        教会模型在什么场景下应该调用什么工具。
        """
        tool_samples = [
            TrainingSample(
                instruction="帮我看看A区机房的整体状态。",
                output=(
                    "**【思考】** 用户想了解A区的综合状态，我需要查询基础设施信息。\n"
                    "**【行动】** 调用工具 `query_infrastructure`，参数: query='A区'\n"
                    "**【观察】** 根据返回数据进行分析并汇总。"
                ),
            ),
            TrainingSample(
                instruction="当前制冷效率正常吗？需不需要调整空调？",
                output=(
                    "**【思考】** 用户关心的是制冷效率和是否需要调整，我需要分析全部区域的冷却状态。\n"
                    "**【行动】** 调用工具 `analyze_cooling`，参数: zone='all'\n"
                    "**【观察】** 根据送回风温差和机柜负载率进行综合评估。"
                ),
            ),
            TrainingSample(
                instruction="有没有外部人员进入机房？安全吗？",
                output=(
                    "**【思考】** 用户关心安防情况，我需要分析门禁出入记录。\n"
                    "**【行动】** 调用工具 `analyze_security`，参数: hours=2\n"
                    "**【观察】** 识别外部人员进场情况并生成巡检建议。"
                ),
            ),
            TrainingSample(
                instruction="核心交换机链路聚合失效怎么排查？",
                output=(
                    "**【思考】** 这是一个故障处置问题，我需要检索专家知识库中的 SOP。\n"
                    "**【行动】** 调用工具 `search_expert_knowledge`，参数: question='链路聚合失效排查'\n"
                    "**【观察】** 返回标准处置步骤供运维人员参考。"
                ),
            ),
            TrainingSample(
                instruction="SVR-003 一直高负载，帮我重启一下。",
                output=(
                    "**【思考】** 用户请求重启服务器，这属于高危操作。\n"
                    "**【安全拦截】** restart_server 为 DANGER 级别工具，"
                    "需要值班主管在审批界面中确认后方可执行。\n"
                    "**【建议】** 在重启前，建议先通过 query_infrastructure 确认该服务器上的业务负载情况，"
                    "避免影响正在运行的关键业务。"
                ),
            ),
        ]

        self.samples.extend(tool_samples)
        print(f"✅ 生成了 {len(tool_samples)} 条工具调用训练样本。")

    def save(self):
        """将所有训练样本导出为 JSONL 文件"""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.output_path, "w", encoding="utf-8") as f:
            for sample in self.samples:
                f.write(json.dumps(asdict(sample), ensure_ascii=False) + "\n")

        print(f"✅ 已保存 {len(self.samples)} 条训练样本至 {self.output_path}")

    def preview(self, n: int = 3):
        """预览前 n 条样本"""
        for i, s in enumerate(self.samples[:n], 1):
            print(f"\n{'━'*50}")
            print(f"  样本 #{i}")
            print(f"  Q: {s.instruction[:80]}")
            print(f"  A: {s.output[:120]}...")


# ── 主入口：运行数据准备全流程 ────────────────────────────
if __name__ == "__main__":
    preparer = DataPreparer(output_path="finetune/train_data.jsonl")

    # 1. 从 SOP 手册提取
    preparer.load_from_sop_markdown("data/expert_knowledge.md")

    # 2. 从故障工单提取（如果有）
    preparer.load_from_tickets_json("data/sample_tickets.json")

    # 3. 生成工具调用训练数据
    preparer.generate_tool_calling_samples()

    # 4. 预览
    preparer.preview(5)

    # 5. 导出
    preparer.save()
