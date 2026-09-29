"""
金枢 (Jin-Shu) - 全链路大模型微调流水线 (SFT + RLHF + DPO)
============================================================
基于 HuggingFace Transformers + PEFT + TRL 框架构建的完整微调管线。
支持全阶段参数高效微调 (LoRA / QLoRA)。

包含三大阶段：
  Phase 1: SFT (Supervised Fine-Tuning) - 监督微调，注入运维领域知识
  Phase 2: RLHF (PPO) - 强化学习，利用奖励模型对齐人类偏好
  Phase 3: DPO (Direct Preference Optimization) - 直接偏好优化，更高效的对齐算法
  - 硬件配置：2x NVIDIA H100 (80GB)
  - 分布式加速：DeepSpeed ZeRO-3 + FlashAttention 2

使用方法 (2张 H100 分布式启动)：
    torchrun --nproc_per_node=2 -m finetune.train_lora \
        --stage sft \
        --base_model "Qwen/Qwen2.5-32B-Instruct" \
        --deepspeed "finetune/ds_config.json"
"""

import argparse
import json
import os

try:
    import torch
    from transformers import (
        AutoModelForCausalLM,
        AutoModelForSequenceClassification,
        AutoTokenizer,
        TrainingArguments,
    )
    from peft import LoraConfig, get_peft_model, TaskType
    from datasets import Dataset
    from trl import SFTTrainer, DPOTrainer, RewardTrainer, PPOTrainer
    HAS_GPU_DEPS = True
except ImportError:
    HAS_GPU_DEPS = False
    print("⚠️ [金枢微调] GPU 依赖未完整安装。")
    print("   本脚本需在配备 GPU 的训练服务器上运行。")
    print("   安装命令: pip install torch transformers peft datasets trl")


# ── 通用模型加载与配置 ─────────────────────────────────────

def load_model_and_tokenizer(base_model: str, use_4bit: bool = True, is_reward_model: bool = False):
    """加载基座模型与分词器，并配置 4-bit 量化"""
    print(f"📦 加载分词器: {base_model}...")
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True, padding_side="right")
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    print(f"📦 加载基座模型 (4bit={use_4bit})...")
    model_kwargs = {
        "trust_remote_code": True,
        # H100 原生支持 bfloat16 和 FlashAttention 2，极大提升 32B 模型的吞吐量
        "torch_dtype": torch.bfloat16,
        "attn_implementation": "flash_attention_2",
    }
    
    # 当使用 DeepSpeed 时，通常由 DS 分配 device，故不强制设 device_map="auto"
    # 除非单卡运行才使用 auto
    if "LOCAL_RANK" not in os.environ:
        model_kwargs["device_map"] = "auto"
    if use_4bit:
        from transformers import BitsAndBytesConfig
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
        )

    if is_reward_model:
        model = AutoModelForSequenceClassification.from_pretrained(base_model, num_labels=1, **model_kwargs)
    else:
        model = AutoModelForCausalLM.from_pretrained(base_model, **model_kwargs)
        
    model.config.use_cache = False
    return model, tokenizer


def get_lora_config(r=16, alpha=32, task_type=TaskType.CAUSAL_LM):
    """获取通用的 LoRA 配置"""
    return LoraConfig(
        task_type=task_type,
        r=r,
        lora_alpha=alpha,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"], 
        bias="none",
    )


# ═══════════════════════════════════════════════════════════
# Phase 1: SFT (Supervised Fine-Tuning) 监督微调
# ═══════════════════════════════════════════════════════════

def train_sft(args):
    """第一阶段：使用 SFTTrainer 注入垂直领域（数据中心运维）知识"""
    print("\n" + "=" * 50 + "\n🚀 启动 Phase 1: SFT 监督微调\n" + "=" * 50)
    model, tokenizer = load_model_and_tokenizer(args.base_model, args.use_4bit)
    
    # 构建适合 SFT 的格式化文本
    raw_data = []
    with open(args.data_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                sample = json.loads(line)
                user_msg = f"{sample['instruction']}\n\n{sample.get('input', '')}"
                text = (
                    f"<|im_start|>system\n你是金枢，智能运维助手。<|im_end|>\n"
                    f"<|im_start|>user\n{user_msg}<|im_end|>\n"
                    f"<|im_start|>assistant\n{sample['output']}<|im_end|>"
                )
                raw_data.append({"text": text})
                
    dataset = Dataset.from_list(raw_data)
    
    training_args = TrainingArguments(
        output_dir=os.path.join(args.output_dir, "sft"),
        per_device_train_batch_size=args.batch_size,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        bf16=True, # H100 强推 bfloat16
        logging_steps=10,
        save_strategy="epoch",
        deepspeed=args.deepspeed, # 接入 DeepSpeed ZeRO 配置
        gradient_checkpointing=True, # Qwen2.5-32B 必须开启梯度检查点防止 OOM
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=get_lora_config(),
        dataset_text_field="text",
        max_seq_length=2048,
        tokenizer=tokenizer,
        args=training_args,
    )
    
    trainer.train()
    trainer.model.save_pretrained(os.path.join(args.output_dir, "sft_final"))
    tokenizer.save_pretrained(os.path.join(args.output_dir, "sft_final"))
    print("✅ SFT 训练完成！")


# ═══════════════════════════════════════════════════════════
# Phase 2: RLHF (PPO + Reward Model) 基于人类反馈的强化学习
# ═══════════════════════════════════════════════════════════

def train_rlhf_reward(args):
    """第二阶段 (A)：训练奖励模型 (Reward Model)"""
    print("\n" + "=" * 50 + "\n🚀 启动 Phase 2(A): RLHF 奖励模型训练\n" + "=" * 50)
    # 奖励模型是一个序列分类模型，输出评分
    model, tokenizer = load_model_and_tokenizer(args.base_model, args.use_4bit, is_reward_model=True)
    
    # 奖励模型需要 chosen (好回复) 和 rejected (坏回复)
    # 假定数据为: {"prompt": "...", "chosen": "好的建议...", "rejected": "危险的建议..."}
    dataset = Dataset.from_json(args.dpo_data_path)

    training_args = TrainingArguments(
        output_dir=os.path.join(args.output_dir, "reward_model"),
        per_device_train_batch_size=args.batch_size,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        bf16=True, # H100
        deepspeed=args.deepspeed,
        gradient_checkpointing=True,
    )

    trainer = RewardTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        peft_config=get_lora_config(task_type=TaskType.SEQ_CLS),
        args=training_args,
    )
    
    trainer.train()
    trainer.model.save_pretrained(os.path.join(args.output_dir, "rm_final"))
    print("✅ Reward Model 训练完成！")

# 注意：PPO 阶段代码量巨大且极其消耗显存，通常需要分布式集群。
# 这里仅作流水线架构的占位展示。
def train_rlhf_ppo(args):
    """第二阶段 (B)：使用 PPOTrainer 进行强化学习策略优化"""
    print("\n" + "=" * 50 + "\n🚀 启动 Phase 2(B): PPO 强化学习 (架构展示)\n" + "=" * 50)
    print("⚠️ 提示：PPO 需要同时加载 4 个模型（Actor, Reference, Reward, Value）。")
    print("在实际生产中，对于运维对话这种确定性任务，我们更推荐使用 DPO 替代 PPO。")


# ═══════════════════════════════════════════════════════════
# Phase 3: DPO (Direct Preference Optimization) 直接偏好优化
# ═══════════════════════════════════════════════════════════

def train_dpo(args):
    """
    第三阶段：DPO 微调 (业界当前主流，完美替代 PPO)。
    无需单独训练 Reward Model，直接在交叉熵损失中融入偏好概率。
    极大地节约了显存和训练时间。
    """
    print("\n" + "=" * 50 + "\n🚀 启动 Phase 3: DPO 直接偏好优化\n" + "=" * 50)
    
    # DPO 需要基于 SFT 后的模型进行
    sft_model_path = os.path.join(args.output_dir, "sft_final")
    if not os.path.exists(sft_model_path):
        print(f"⚠️ 找不到 SFT 模型 ({sft_model_path})，回退使用基座模型。")
        sft_model_path = args.base_model
        
    model, tokenizer = load_model_and_tokenizer(sft_model_path, args.use_4bit)
    
    # DPO 数据格式要求：prompt, chosen, rejected
    # 示例：
    # prompt: "重启服务器命令是什么？"
    # chosen: "由于这是高危操作，请您确认...并执行系统级审批流" (符合金枢的安全设定)
    # rejected: "直接输入 reboot 即可。" (不符合设定，易引发灾难)
    dataset = Dataset.from_json(args.dpo_data_path)

    training_args = TrainingArguments(
        output_dir=os.path.join(args.output_dir, "dpo"),
        per_device_train_batch_size=args.batch_size // 2, # DPO 需要同时前向计算两次，Batch 减半
        learning_rate=args.lr * 0.1, # DPO 学习率通常比 SFT 小一个数量级
        num_train_epochs=args.epochs,
        bf16=True, # H100
        remove_unused_columns=False,
        deepspeed=args.deepspeed,
        gradient_checkpointing=True,
    )

    trainer = DPOTrainer(
        model,
        ref_model=None, # TRL 内部会自动复制一份 adapter 作为参考模型
        peft_config=get_lora_config(),
        args=training_args,
        beta=0.1, # DPO 偏好散度权重 (KL Penalty)
        train_dataset=dataset,
        tokenizer=tokenizer,
    )
    
    trainer.train()
    trainer.model.save_pretrained(os.path.join(args.output_dir, "dpo_final"))
    tokenizer.save_pretrained(os.path.join(args.output_dir, "dpo_final"))
    print("✅ DPO 对齐训练完成！模型安全性与指令遵从度已提升。")


# ── 路由分发 ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="金枢全链路大模型微调流水线 (SFT -> RLHF -> DPO)")
    parser.add_argument("--stage", type=str, required=True, choices=["sft", "reward", "ppo", "dpo"],
                        help="选择训练阶段：sft, reward, ppo, dpo")
    parser.add_argument("--base_model", type=str, default="Qwen/Qwen2.5-32B-Instruct")
    parser.add_argument("--data_path", type=str, default="finetune/train_data.jsonl", help="SFT 训练数据")
    parser.add_argument("--dpo_data_path", type=str, default="finetune/dpo_data.jsonl", help="RLHF/DPO 偏好对齐数据")
    parser.add_argument("--output_dir", type=str, default="finetune/output/jinshu_qwen32b")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=2e-5) # 32B模型学习率调低
    parser.add_argument("--use_4bit", action="store_true", default=False, help="H100 显存充足，建议关闭 4bit 走全 bf16")
    parser.add_argument("--deepspeed", type=str, default="finetune/ds_config.json", help="DeepSpeed 配置文件路径")
    
    args = parser.parse_args()

    if not HAS_GPU_DEPS:
        exit(1)

    if args.stage == "sft":
        train_sft(args)
    elif args.stage == "reward":
        train_rlhf_reward(args)
    elif args.stage == "ppo":
        train_rlhf_ppo(args)
    elif args.stage == "dpo":
        train_dpo(args)
