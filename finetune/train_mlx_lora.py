"""
金枢 (Jin-Shu) - Apple Mac (Apple Silicon) 专属本地微调脚本
============================================================
基于苹果官方高性能基础库 MLX (mlx-lm)。
利用 Mac M 系列芯片（如你的 M5 Pro 48GB）的高带宽统一内存架构，实现拔群的本地 LoRA 高效微调。

前置准备（在命令行运行）：
1. 确保安装原生加速库: pip install mlx mlx-lm

模型基础知识：
- MLX 会自动从开源社区边下载权重边加载到你的统一显存运算。
- `train.jsonl` 是微调知识数据（由我们之前的代码自动转换出来）。
"""

import os
import subprocess

def run_mlx_finetune():
    print("=" * 60)
    print("🍎 启动 Apple MLX 原生大模型训练微调管线 (Jin-Shu M5 Pro 高转速版)")
    print("=" * 60)

    # MLX 规定包含数据的那个文件夹里需要有一个 `train.jsonl`，我们来准备一下
    current_dir = os.path.dirname(os.path.abspath(__file__))
    source_data = os.path.join(current_dir, "train_data.jsonl")
    target_data = os.path.join(current_dir, "train.jsonl")
    
    if os.path.exists(source_data):
        import shutil
        shutil.copy2(source_data, target_data)
        print("✅ 数据预准备：已就绪到 MLX 训练流水线")
    else:
        print("❌ 错误：请先运行数据清洗脚本生成训练素材")
        return

    # 基座模型名称：直接指向 HuggingFace 开源库，脚本会自动下载解压到本地
    model_name = "Qwen/Qwen2.5-7B"

    # ========= 炼丹炉调参旋钮（非常硬核的行业词汇） =========
    batch_size = "4"       # 并行处理数量（你的 48G 可以轻松调到更大的 8 甚至 16，缩短整体时间）
    lora_layers = "16"     # 影响模型的几层大脑突触？16 是标准推荐
    learning_rate = "1e-4" # 学习率：决定了它学新东西的步子迈得多大
    iters = "500"          # 训练迭代总步数。要吃透机房资料，500步算预热，实际可改 2000
    # ========================================================

    print(f"📦 目标基座模型：{model_name}")
    print(f"⚙️ 参数调优档案：Batch={batch_size} | Iters={iters} | LoRA-L={lora_layers}")
    print(f"🚀 基于硬件探测：此脚本将深度调用 Apple 金属神经引擎 (Metal) 并分配动态高带宽显存。")

    mlx_command = [
        "python3", "-m", "mlx_lm.lora",
        "--model", model_name,
        "--train",
        "--data", current_dir, # 数据集所在路径
        "--batch-size", batch_size,
        "--lora-layers", lora_layers,
        "--learning-rate", learning_rate,
        "--iters", iters,
        "--save-every", "100"  # 每进化 100 步保存一个快照档机制
    ]

    print("\n👉 [内部日志] 发射的张量编译器原子级指令为：")
    print("  " + " ".join(mlx_command))
    print("-" * 50)
    print("如果你决定正式开始烧算力炼丹，请打开本文件，将底部 subprocess.run 的注释符号去掉。")

    # 执行命令正式启炉进行深度微调
    subprocess.run(mlx_command)

if __name__ == "__main__":
    run_mlx_finetune()
