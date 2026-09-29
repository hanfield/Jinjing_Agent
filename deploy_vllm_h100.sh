#!/bin/bash
# 金枢 (Jin-Shu) - 2x H100 分布式推理启动脚本 (vLLM)
# ========================================================
# 利用 vLLM 框架的 Tensor Parallelism (TP张量并行)，
# 将 Qwen2.5-32B 切分到 2 张 H100 80GB 上运行，实现极致推理吞吐量。

echo "🚀 启动分布式推理引擎 (vLLM on 2x H100)"

# 指定模型路径 (如果是微调后的模型，请指向 merge 后的权重目录)
MODEL_PATH="Qwen/Qwen2.5-32B-Instruct"
# 如果使用了 LoRA，vLLM 支持直接挂载 LoRA 适配器，无需提前 Merge
LORA_PATH="finetune/output/jinshu_qwen32b/dpo_final"

# 启动 vLLM OpenAI 兼容 Server
# 参数解析：
# --tensor-parallel-size 2 : 开启 2 张显卡张量并行
# --gpu-memory-utilization 0.95 : 压榨 H100 的 80GB 显存，留 5% 给系统
# --max-model-len 32768 : 运维日志上下文通常较长，Qwen2.5支持最高 128K
# --dtype bfloat16 : H100 原生支持，保证精度和速度
# --enable-lora : 允许动态挂载 LoRA 权重

CUDA_VISIBLE_DEVICES=0,1 python -m vllm.entrypoints.openai.api_server \
    --model $MODEL_PATH \
    --tensor-parallel-size 2 \
    --gpu-memory-utilization 0.95 \
    --max-model-len 32768 \
    --dtype bfloat16 \
    --enable-lora \
    --lora-modules jinshu-v1=$LORA_PATH \
    --port 8000 \
    --host 0.0.0.0

echo "✅ vLLM 引擎已启动，对外暴露兼容 OpenAI 的 HTTP API 接口：http://localhost:8000/v1"
