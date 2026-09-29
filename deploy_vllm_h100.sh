#!/bin/bash
# 金枢 (Jin-Shu) - 2x H100 分布式推理启动脚本 (vLLM with Reasoning Support)
# ========================================================
# 利用 vLLM 框架的 Tensor Parallelism (TP张量并行)，
# 将 QwQ-32B / DeepSeek-R1-Distill-Qwen-32B 切分到 2 张 H100 80GB 上运行。
# 开启原生长思维链抽取器 (--reasoning-parser deepseek_r1)，实现极致推理吞吐与自反思能力。

echo "🚀 启动原生推理大模型引擎 (vLLM on 2x H100 - Reasoning Edition)"

# 指定模型路径 (推荐 QwQ-32B 或 DeepSeek-R1-Distill-Qwen-32B)
MODEL_PATH="${MODEL_PATH:-Qwen/QwQ-32B}"
# 如果使用了 LoRA，vLLM 支持直接挂载 LoRA 适配器，无需提前 Merge
LORA_PATH="${LORA_PATH:-finetune/output/jinshu_qwq32b/dpo_final}"

# 启动 vLLM OpenAI 兼容 Server
# 参数解析：
# --tensor-parallel-size 2 : 开启 2 张显卡张量并行
# --gpu-memory-utilization 0.95 : 压榨 H100 的 80GB 显存，留 5% 给系统
# --max-model-len 32768 : 容纳长思维链深度反思与万行机房遥测日志
# --dtype bfloat16 : H100 原生支持，保证精度和速度
# --reasoning-parser deepseek_r1 : 原生解析 <think> 标签并映射为 OpenAI 协议的 reasoning_content
# --enable-prefix-caching : 开启前缀缓存，多智能体共享的系统提示词与黑板态势无需重复计算，TTFT 降低 50%+
# --enable-lora : 允许动态挂载 LoRA 权重

CUDA_VISIBLE_DEVICES=0,1 python -m vllm.entrypoints.openai.api_server \
    --model $MODEL_PATH \
    --tensor-parallel-size 2 \
    --gpu-memory-utilization 0.95 \
    --max-model-len 32768 \
    --dtype bfloat16 \
    --reasoning-parser deepseek_r1 \
    --enable-prefix-caching \
    --enable-lora \
    --lora-modules jinshu-v1=$LORA_PATH \
    --port 8000 \
    --host 0.0.0.0


echo "✅ vLLM 原生推理引擎已启动，对外暴露兼容 OpenAI 的 HTTP API 接口：http://localhost:8000/v1"

