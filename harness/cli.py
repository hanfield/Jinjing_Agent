"""
金枢 2.0 (Jin-Shu OS) - Standard Harness CLI (标准命令行评测总调度台)
======================================================================
提供高度模块化与参数化的命令行调用能力。支持指定配置文件、基准任务 ID、驱动适配器
以及输出格式，实现真正的工业级自动化评测大盘。
"""

import os
import argparse
import asyncio
import json
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

from harness.tasks.task_registry import TaskRegistry
from harness.environments.sandbox_proxy import SandboxProxyHarness
from harness.adapters.jinshu_adapter import JinShuAgentAdapter
from harness.evaluators.metrics_engine import MetricsEngine
from harness.utils.logger import logger



async def run_harness_cli(config_path: str, task_id: str = None) -> Dict[str, Any]:
    """执行命令行评测主流程"""
    registry = TaskRegistry(config_path)
    sandbox = SandboxProxyHarness()
    adapter = JinShuAgentAdapter(sandbox)
    evaluator = MetricsEngine()

    logger.info("=" * 70)
    logger.info(f"🚀 金枢 2.0 (Jin-Shu OS) - 工业级智能体评测大盘 (Harness CLI)")
    logger.info(f"   - 测试套件: {registry.suite_metadata.get('suite_name')} (v{registry.suite_metadata.get('version')})")
    logger.info(f"   - 套件描述: {registry.suite_metadata.get('description')}")
    logger.info("=" * 70)

    tasks_to_run = [registry.get_task(task_id)] if task_id else registry.list_tasks()
    if not tasks_to_run or not tasks_to_run[0]:
        logger.error(f"❌ 错误：未找到指定任务 ID [{task_id}]")
        return {}


    overall_results = []
    
    # 1. 创建企业级评测批次 (Run ID)
    run_id = evaluator.create_run(registry.suite_metadata.get("suite_name"))
    
    w_eng = registry.suite_metadata.get("weight_eng", 0.6)
    w_judge = registry.suite_metadata.get("weight_judge", 0.4)

    for task in tasks_to_run:
        logger.info(f"\n🔄 [Harness 总台] 正在加载基准测试用例: [{task.task_id}] ...")
        logger.info(f"   - 测试类别: {task.category}")
        logger.info(f"   - 用户提示词: {task.user_prompt}")
        logger.info(f"   - 黄金指标: 期望专家={task.golden_metrics.expected_experts}, 期望工具={task.golden_metrics.expected_tools}")

        logger.info("\n🚀 [Harness 驱动层] 正在通过透明沙箱代理驱动 Agent 执行流...")
        exec_result = await adapter.run_task(task)

        logger.info("\n⚖️ [Harness 评估层] 正在进行硬工程指标与大模型裁判双核评估...")
        eng_metrics = evaluator.evaluate_engineering_metrics(task, exec_result, weight=w_eng)
        judge_metrics = await evaluator.evaluate_llm_judge(task, exec_result)

        final_score = (eng_metrics["engineering_score"] * w_eng) + (judge_metrics["judge_score"] * w_judge)
        passed = final_score >= 85.0 and eng_metrics["approval_pass"]

        logger.info(f"\n📊 [{task.task_id} 评测报告]:")
        logger.info(f"   - 综合评分: {final_score:.1f} / 100.0")
        logger.info(f"   - 工程指标得分: {eng_metrics['engineering_score']:.1f} (工具召回率: {eng_metrics['tool_recall']*100:.0%} | 专家匹配度: {eng_metrics['expert_match']*100:.0%})")
        logger.info(f"   - 大模型裁判得分: {judge_metrics['judge_score']:.1f} ({judge_metrics['judge_comment']})")
        logger.info(f"   - 首字时延 TTFT: {eng_metrics['ttft_ms']:.1f} ms | 总此时延: {eng_metrics['execution_latency_ms']:.1f} ms")
        logger.info(f"   - 评测结论: {'✅ 基准测试通过 (PASSED)' if passed else '❌ 基准测试未达标 (FAILED)'}")


        evaluator.persist_flywheel(run_id, task, exec_result, passed, final_score, eng_metrics, judge_metrics)
        
        overall_results.append({
            "task_id": task.task_id, "passed": passed, "final_score": final_score,
            "metrics": {**eng_metrics, **judge_metrics}
        })

    await evaluator.close()
    return {"suite": registry.suite_metadata.get("suite_name"), "run_id": run_id, "results": overall_results}


def main():
    parser = argparse.ArgumentParser(description="金枢 2.0 (Jin-Shu OS) - 工业级智能体评测命令行工具")
    parser.add_argument("--config", type=str, default=os.path.join(os.path.dirname(__file__), "configs", "default_eval.json"), help="基准测试套件配置文件路径")
    parser.add_argument("--task", type=str, default=None, help="指定运行的单一 Benchmark Task ID")
    args = parser.parse_args()

    asyncio.run(run_harness_cli(args.config, args.task))


if __name__ == "__main__":
    main()
