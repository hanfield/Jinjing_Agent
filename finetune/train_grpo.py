"""
金枢 3.0 (Jin-Shu OS) - 规则可验证强化学习训练管线 (GRPO / RLVR Pipeline)
========================================================================
基于 DeepSeek-R1 / QwQ 提出的 Group Relative Policy Optimization (GRPO) 算法，
彻底摆脱高昂且容易出现奖励黑客 (Reward Hacking) 的神经价值模型 (Critic Model)。

针对数据中心复杂根因排障场景，通过一组轻量且数学上严格的【规则可验证奖励函数 (RLVR)】，
直接在生成采样群组 (Group of G completions) 内部计算相对优势 (Relative Advantage):
    A_i = (R_i - mean(R)) / (std(R) + eps)

包含四大核心规则奖励函数：
  1. reasoning_structure_reward: 强化长思维链规范 (<think>...</think> 闭环与思考深度)
  2. root_cause_accuracy_reward: 故障靶点与底层物理根因的命中率验证 (针对 Ground-Truth)
  3. safety_constraint_reward:   高危运维指令的心智副作用预演与审批门前置声明约束
  4. sop_actionable_reward:      应急响应卡片 (SOP) 的结构化完整度与可执行性验证

硬件基准：2x NVIDIA H100 (80GB) | 支持 FlashAttention-2 + ZeRO-3 / bfloat16
"""

import argparse
import json
import os
import re
from typing import List, Dict, Any

try:
    import torch
    from transformers import AutoTokenizer
    from peft import LoraConfig, TaskType
    from datasets import Dataset
    from trl import GRPOConfig, GRPOTrainer
    HAS_GPU_DEPS = True
except ImportError:
    HAS_GPU_DEPS = False


# ==============================================================================
# 1. 规则可验证奖励函数 (Rule-Based Verifiable Rewards)
# ==============================================================================

def reasoning_structure_reward(completions: List[str], **kwargs) -> List[float]:
    """
    【思维链结构规范奖励】
    验证模型回答是否具备清晰的 <think>...</think> 内部推理过程，
    且在思维链结束后给出明确的面向运维主管的结论与操作建议。
    """
    rewards = []
    for text in completions:
        score = 0.0
        # 1. 必须包含完整的闭合 <think> 标签
        has_think_start = "<think>" in text
        has_think_end = "</think>" in text

        if has_think_start and has_think_end:
            # 基础闭环奖励
            score += 0.5

            # 提取思维链内容
            think_match = re.search(r"<think>([\s\S]*?)</think>", text)
            if think_match:
                think_content = think_match.group(1).strip()
                # 思维深度梯次加分
                if len(think_content) > 30:
                    score += 0.3
                if len(think_content) > 100:
                    score += 0.4
                if len(think_content) > 300:
                    score += 0.5
                # 包含假设验证词汇（如：假设、排查、如果是、验证、查证）
                hypothesis_words = ["假设", "排查", "验证", "上游", "物理根因", "诱因", "指标"]
                matched_words = sum(1 for w in hypothesis_words if w in think_content)
                score += min(0.5, matched_words * 0.1)

            # 2. 标签后必须有最终面向用户的结论
            post_think = text.split("</think>")[-1].strip()
            if len(post_think) > 10:
                score += 0.5
        elif has_think_start and not has_think_end:
            # 思维链未正常截断惩罚
            score -= 1.0
        else:
            # 缺乏长思维链惩罚
            score -= 0.5

        rewards.append(float(score))
    return rewards


def root_cause_accuracy_reward(completions: List[str], ground_truth: List[str] = None, **kwargs) -> List[float]:
    """
    【根因准确度可验证奖励】
    将模型推断出的结论与拓扑图谱标注的 Ground-Truth 真实物理诱因比对。
    """
    rewards = []
    if ground_truth is None:
        ground_truth = [""] * len(completions)

    for text, gt in zip(completions, ground_truth):
        score = 0.0
        if not gt:
            rewards.append(0.0)
            continue

        gt_keywords = [k.strip() for k in gt.split(",") if k.strip()]
        matched_count = 0
        for kw in gt_keywords:
            if kw in text:
                matched_count += 1

        if gt_keywords:
            match_ratio = matched_count / len(gt_keywords)
            # 全中得满分 2.0 分
            score = match_ratio * 2.0
            if match_ratio == 1.0:
                score += 0.5  # 额外完全匹配奖励

        rewards.append(float(score))
    return rewards


def safety_constraint_reward(completions: List[str], **kwargs) -> List[float]:
    """
    【高危运维安全红线约束奖励】
    数据中心绝对不能无审批直接执行破坏性指令（断电、强杀、物理机重启）。
    - 凡是提出执行重启或下线方案，必须声明需要主管审批 (Human-in-the-Loop)。
    - 必须包含对 Quorum / 多数派仲裁与下游 SLA 冲击的心智预演。
    """
    rewards = []
    danger_actions = ["restart_server", "reboot", "重启", "下线", "power_off", "断电", "rm -rf"]

    for text in completions:
        score = 0.0
        has_danger = any(act in text for act in danger_actions)

        if has_danger:
            # 1. 检查是否有前置审批声明
            approval_hints = ["审批", "值班主管", "授权", "确认", "approval", "高危操作", "风险声明"]
            has_approval = any(h in text for h in approval_hints)

            # 2. 检查是否有副作用与 SLA 冲击心智预演
            impact_hints = ["SLA", "冲击", "多数派", "冗余", "备用", "迁移", "Quorum", "容灾"]
            has_impact_check = any(h in text for h in impact_hints)

            if has_approval and has_impact_check:
                score += 1.5  # 严谨合规
            elif has_approval:
                score += 0.5
            else:
                score -= 2.0  # 严重违规：私自越权执行高危操作
        else:
            # 无高危操作时，保持只读安全
            score += 0.2

        rewards.append(float(score))
    return rewards


def sop_actionable_reward(completions: List[str], **kwargs) -> List[float]:
    """
    【SOP 结构化与可执行性奖励】
    评估是否输出了结构化的标准应急操作卡片 (SOP)。
    """
    rewards = []
    sop_markers = ["【应急处置 SOP】", "【处置建议】", "步骤 1", "1.", "核查命令", "恢复验证"]

    for text in completions:
        score = 0.0
        matches = sum(1 for m in sop_markers if m in text)
        if matches >= 3:
            score += 1.0
        elif matches >= 1:
            score += 0.5

        # 检查是否包含具体的命令行指示（如 df, du, ping, curl, systemctl 等）
        cmd_hints = ["df", "systemctl", "kubectl", "docker", "top", "free", "ssh", "grep"]
        if any(c in text for c in cmd_hints):
            score += 0.5

        rewards.append(float(score))
    return rewards


def compute_combined_rewards(completions: List[str], ground_truth: List[str] = None) -> Dict[str, List[float]]:
    """组合计算所有规则奖励，并输出各分项指标"""
    r_struct = reasoning_structure_reward(completions)
    r_root = root_cause_accuracy_reward(completions, ground_truth=ground_truth)
    r_safe = safety_constraint_reward(completions)
    r_sop = sop_actionable_reward(completions)

    totals = [
        s + r + saf + sop
        for s, r, saf, sop in zip(r_struct, r_root, r_safe, r_sop)
    ]

    return {
        "total_reward": totals,
        "structure_reward": r_struct,
        "root_cause_reward": r_root,
        "safety_reward": r_safe,
        "sop_reward": r_sop,
    }


def compute_group_relative_advantages(rewards: List[float], eps: float = 1e-6) -> List[float]:
    """
    计算 GRPO 群组相对优势 A_i:
    A_i = (R_i - mean(R)) / (std(R) + eps)
    """
    if not rewards:
        return []
    n = len(rewards)
    if n == 1:
        return [0.0]
    mean = sum(rewards) / n
    variance = sum((r - mean) ** 2 for r in rewards) / n
    std = (variance ** 0.5)
    return [(r - mean) / (std + eps) for r in rewards]


# ==============================================================================
# 2. 数据集加载与格式化
# ==============================================================================

def load_grpo_dataset(data_path: str) -> List[Dict[str, Any]]:
    """加载用于 GRPO 强化学习探索的工单提示词数据集"""
    dataset = []
    if not os.path.exists(data_path):
        # 默认构建几条高质量典型数据中心靶场样本
        return [
            {
                "prompt": "【紧急告警】动环监控探测到 A 区 CRAC-A01 冷凝水泄漏告警，同时 RACK-A02 内部服务器 SVR-001 温度飙升至 31.5°C。请给出排查思维与处置步骤。",
                "ground_truth": "冷凝水,CRAC-A01,排水管破裂,迁移任务"
            },
            {
                "prompt": "【故障巡查】SVR-003 磁盘使用率达到 99.8%，核心支付应用交易延时突增。请分析并给出解决方案。",
                "ground_truth": "日志溢出,du,rm,归档,日志轮转"
            },
            {
                "prompt": "【供电异常】UPS-A01 逆变器输出纹波达到 8.2%，母线电压存在跌落风险。请推演诱因与应急方案。",
                "ground_truth": "滤波电容,旁路供电,倒闸,带电更换"
            }
        ]

    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            # 兼容多种数据格式
            prompt = item.get("prompt") or item.get("user_message") or ""
            gt = item.get("ground_truth") or item.get("root_cause") or ""
            if prompt:
                dataset.append({"prompt": prompt, "ground_truth": gt})

    return dataset


# ==============================================================================
# 3. GRPO 训练驱动核心
# ==============================================================================

def run_grpo_training(
    model_name: str,
    data_path: str,
    output_dir: str,
    group_size: int = 4,
    learning_rate: float = 1e-6,
    num_train_epochs: int = 3,
    use_lora: bool = True
):
    """驱动 HuggingFace TRL GRPOTrainer 执行强化学习训练"""
    if not HAS_GPU_DEPS:
        print("❌ 缺少 GPU 训练依赖 (torch / trl / peft)。")
        print("   在离线 CPU 环境中，您可以使用验证模块 compute_combined_rewards 进行奖励测试。")
        return

    print("=" * 70)
    print("🚀 [金枢 3.0] 启动 GRPO 规则可验证强化学习流水线")
    print(f"   - 基座模型: {model_name}")
    print(f"   - 采样群组大小 G: {group_size}")
    print(f"   - 学习率: {learning_rate}")
    print(f"   - 输出目录: {output_dir}")
    print("=" * 70)

    raw_data = load_grpo_dataset(data_path)
    hf_dataset = Dataset.from_list(raw_data)

    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # LoRA 配置
    peft_config = None
    if use_lora:
        peft_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=16,
            lora_alpha=32,
            lora_dropout=0.05,
            target_modules=[
                "q_proj", "k_proj", "v_proj", "o_proj",
                "gate_proj", "up_proj", "down_proj"
            ],
            bias="none"
        )

    # GRPO 配置
    training_args = GRPOConfig(
        output_dir=output_dir,
        learning_rate=learning_rate,
        num_train_epochs=num_train_epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        num_generations=group_size,  # 每个 prompt 采样 G 个轨迹
        max_prompt_length=1024,
        max_completion_length=2048,
        temperature=0.7,
        bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
        logging_steps=5,
        save_strategy="epoch",
        report_to="none"
    )

    # 包装奖励函数为 TRL 标准签名
    def trl_reward_func(prompts, completions, **kwargs):
        # 从 dataset 传递的 metadata 中提取 ground_truth
        ground_truth = kwargs.get("ground_truth", ["" for _ in completions])
        res = compute_combined_rewards(completions, ground_truth=ground_truth)
        return res["total_reward"]

    trainer = GRPOTrainer(
        model=model_name,
        reward_funcs=[trl_reward_func],
        args=training_args,
        train_dataset=hf_dataset,
        peft_config=peft_config,
    )

    print("🔥 开始执行策略群组梯度迭代...")
    trainer.train()
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"✅ GRPO 策略微调完成，模型已保存至: {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="金枢 3.0 GRPO 强化学习训练与奖励验证")
    parser.add_argument("--model", type=str, default="Qwen/QwQ-32B", help="基座模型标识")
    parser.add_argument("--data", type=str, default="finetune/train_data.jsonl", help="训练集路径")
    parser.add_argument("--output", type=str, default="finetune/output/grpo_model", help="输出路径")
    parser.add_argument("--group_size", type=int, default=4, help="每个 prompt 生成的采样群组数 (G)")
    parser.add_argument("--eval_only", action="store_true", help="仅运行规则奖励模拟验证")
    args = parser.parse_args()

    if args.eval_only:
        print("🧪 [GRPO 规则奖励验证测试]")
        mock_completions = [
            # 样本 A: 优秀的长思维链，找到根因且前置声明审批
            "<think>首先审查黑板中的冷凝水告警，机柜温度达 31.5°C 正在逼近宕机阈值。判断为空调排水管破裂导致，需要立即迁移 SVR-001 任务。由于重启物理主机涉及金融业务中断风险，必须前置触发值班主管审批，并预估 Quorum 与 SLA 冲击。</think>【应急处置 SOP】\n步骤 1. 隔离故障支路排水阀；\n步骤 2. 调度备用空调冷量；\n步骤 3. 申请主管授权，执行任务平滑迁移并恢复验证。",
            # 样本 B: 缺少思维链，私自暴力执行重启
            "我直接执行 restart_server 重启 SVR-001，然后再看看情况。",
        ]
        gts = ["冷凝水,排水管,迁移任务", "冷凝水,排水管,迁移任务"]
        res = compute_combined_rewards(mock_completions, ground_truth=gts)
        advs = compute_group_relative_advantages(res["total_reward"])

        for i, (txt, tot, adv) in enumerate(zip(mock_completions, res["total_reward"], advs)):
            print(f"\n--- 样本 {i+1} ---")
            print(f"文本截断: {txt[:60]}...")
            print(f"结构分: {res['structure_reward'][i]} | 根因分: {res['root_cause_reward'][i]} | 安全分: {res['safety_reward'][i]} | SOP分: {res['sop_reward'][i]}")
            print(f"总奖励 (R): {tot:.2f} | 群组相对优势 (A_i): {adv:.2f}")
    else:
        run_grpo_training(
            model_name=args.model,
            data_path=args.data,
            output_dir=args.output,
            group_size=args.group_size
        )


if __name__ == "__main__":
    main()
