---
name: jinshu-harness-eval
description: >-
  Use this skill when running automated agent evaluation benchmarks, adding evaluation
  test suites, verifying telemetry, or exporting SFT/DPO training datasets from the SQLite
  Data Flywheel in Jin-Shu OS.
---

# 金枢评测中枢与数据飞轮开发技能 (Jin-Shu Enterprise Harness Evaluation Skill)

本技能指导开发者和测试代理遵循金枢企业级评测工程规范，运行多维度指标评测、沙箱混沌注入及 SQLite 数据飞轮资产提取。

## 适用场景
- 评估新上线的模型权重或 Prompt 版本的任务完成率与 TTFT；
- 在自动化 CI/CD 流水线中进行回归验证；
- 从评测结果中筛选优质轨迹并沉淀为 SFT / DPO 微调语料。

## 核心操作规程

### 1. 执行全量评测基准
通过 CLI 运行默认评测套件：
```bash
python -m harness.cli --config harness/configs/default_eval.json
```

### 2. 执行回归单元测试套件
验证所有底层工具、技能、假说树与上下文工程逻辑：
```bash
pytest harness/tests
```

### 3. 数据水合 (Data Hydration) 与混沌注入 (Chaos Injection)
遵循 `AGENTS.md` 规范：
- **禁止硬编码环境静态数据**：通过 `snapshot_uri` 动态装载生产现场快照或时序数据；
- **沙箱代理与混沌注入**：评估智能体在丢包、延迟抖动及超时异常下的容错与重试表现：
  ```python
  from harness.environments.sandbox import SandboxProxyHarness
  # 在沙箱中注入 20% 的网络超时与抖动
  sandbox = SandboxProxyHarness(failure_rate=0.2, latency_jitter_ms=150)
  ```

### 4. 结构化数据飞轮 (SQLite Flywheel) 查询与导出
评测结果统一沉淀在 `finetune/flywheel.db`，可直接通过 SQL 或数据抽取脚本提取高价值 SFT / DPO 数据对：
```bash
python finetune/prepare_data.py
```
- 查看任务得分分布与工具调用执行链；
- 导出高质量成功对弈轨迹至 `finetune/train_data.jsonl`。
