"""
金枢 2.0 (Jin-Shu OS) - 全栈企业级架构特性验证与演示脚本
==========================================================
运行此脚本，直观体验金枢 2.0 的四大顶尖架构特性：
  1. Multi-Agent 独立智能体并发与事件驱动总线 (BaseAgent & MessageBus)
  2. 黑板总线上下文通信与防污染治理 (Blackboard Incident State)
  3. MCP 零信任工具气隙隔离 (Air-Gap)
  4. 业界标准 Harness 评测支架与 SFT+DPO 数据对齐飞轮 (Harness CLI & Flywheel)
"""

import os
import asyncio
import json
from dotenv import load_dotenv

from engine.core import multi_agent_orchestrator
from harness.cli import run_harness_cli
from engine.blackboard import global_blackboard

load_dotenv()


async def verify_multi_agent_flow():
    """验证 Multi-Agent 编排与黑板通信流"""
    print("\n" + "=" * 70)
    print("🔷 模块一：Multi-Agent 事件驱动总线编排与黑板通信流验证")
    print("=" * 70)

    test_prompt = "金枢，机房值班员发现A区静电地板下有积水告警，同时 RACK-A02 温度异常飙升，请立即处置！"
    print(f"\n📌 [告警输入]: {test_prompt}\n")
    print("-" * 50)

    async for event in multi_agent_orchestrator.run_orchestration_stream(test_prompt):
        if event.get("event") == "start_thinking":
            print(f"\n🔄 [{event.get('expert')}] 正在加载人设与专属 MCP 工具权限，开始推演...")
        elif event.get("event") == "thought":
            print(f"   💡 [{event.get('expert')} 思维链]: {event.get('text')}")
        elif event.get("event") == "tool_call":
            print(f"   🛠️ [{event.get('expert')} 工具调用]: {event.get('name')} | 参数: {event.get('args')}")
        elif event.get("event") == "observation":
            print(f"   📊 [{event.get('expert')} 探针返回]: {event.get('result')}")
        elif event.get("event") == "blackboard_post":
            ev = event.get('evidence', {})
            print(f"\n   📫 [{event.get('expert')} 黑板投递]: 成功写入总线！靶点={ev.get('affected_target')}, TTF红线={ev.get('ttf_minutes')}m, 置信度={ev.get('confidence')}")
        elif event.get("event") == "final_chunk":
            print(event.get("text"), end="", flush=True)

    print("\n" + "-" * 50)
    print("📋 当前黑板总线最终快照预览:")
    print(json.dumps(global_blackboard.export_snapshot(), ensure_ascii=False, indent=2))
    print("=" * 70)


async def verify_agent_harness_flywheel():
    """验证业界标准 Harness CLI 评测与自动化数据飞轮"""
    print("\n" + "=" * 70)
    print("🔷 模块二：业界标准 Harness CLI 评测大盘与数据对齐飞轮验证")
    print("=" * 70)

    config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "harness", "configs", "default_eval.json")
    result = await run_harness_cli(config_path=config_file, task_id="EVAL_HVAC_001")

    print("\n🎉 [评测大盘闭环总结]:")
    print(f"   - 评测套件: {result.get('suite')}")
    print(f"   - 评测用例数: {len(result.get('results', []))}")
    for res in result.get('results', []):
        print(f"   - 用例 [{res.get('task_id')}] 综合打分: {res.get('final_score'):.1f} 分 | 状态: {'✅ 通过 (PASSED)' if res.get('passed') else '❌ 未达标 (FAILED)'}")
    print("=" * 70)


async def main():
    print("=" * 70)
    print("🚀 金枢 2.0 (Jin-Shu OS) - 顶尖企业级 AI 运维底座架构验证大盘")
    print("=" * 70)

    await verify_multi_agent_flow()
    await asyncio.sleep(1)
    await verify_agent_harness_flywheel()

    await multi_agent_orchestrator.close()
    print("\n✨ 金枢 2.0 架构全栈重构与验证圆满完成！")


if __name__ == "__main__":
    asyncio.run(main())
