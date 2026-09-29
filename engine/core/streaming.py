"""
金枢 3.0 - LangGraph 编排适配器 (Streaming Adapter)
===================================================
提供与原 MultiAgentOrchestrator 相同的方法签名与事件输出规范。
将 LangGraph 的 astream 更新输出流转换为前端所需的 NDJSON 格式事件，
实现无缝、零感重构切换。
"""

import uuid
from typing import Any, AsyncIterator

from .graph import jinshu_graph
from .state import make_initial_state


class LangGraphOrchestrator:
    """金枢 3.0 LangGraph 编排适配器"""

    async def run_stream(self, user_message: str, override_messages: Any = None) -> AsyncIterator[dict]:
        """
        开启全新的多智能体协同排障诊断流。
        """
        # 生成唯一 thread_id 作为本次诊断会话标识（等同于原 session_id）
        thread_id = f"thread-{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        # 初始化图状态
        state = make_initial_state(user_message)

        # 启动后台消息总线（保持兼容性）
        from engine.agents.bus import global_message_bus
        from ..blackboard import global_blackboard
        
        await global_message_bus.start()
        global_blackboard.reset()  # 重置旧黑板单例以备后用

        try:
            async for event in self._run_graph_and_stream(state, config, thread_id):
                yield event
        finally:
            await global_message_bus.stop()

    async def resume_stream(self, session_id: str, approved: bool) -> AsyncIterator[dict]:
        """
        恢复并接续由于高危指令拦截挂起的排障诊断流。
        session_id 对应为 LangGraph 的 thread_id。
        """
        thread_id = session_id
        config = {"configurable": {"thread_id": thread_id}}

        # 启动后台消息总线
        from engine.agents.bus import global_message_bus
        await global_message_bus.start()

        try:
            # 1. 将审批结果更新到该 thread_id 对应的 Checkpoint 状态中
            await jinshu_graph.aupdate_state(config, {"approval_result": approved})

            # 2. 恢复图的执行（传递 None 作为输入，LangGraph 自动从检查点恢复）
            async for event in self._run_graph_and_stream(None, config, thread_id):
                yield event
        finally:
            await global_message_bus.stop()

    async def _run_graph_and_stream(self, initial_state: Any, config: dict, thread_id: str) -> AsyncIterator[dict]:
        """核心流式驱动适配器"""
        try:
            # 使用 updates 模式，每次节点执行完返回局部 state 增量时即可获取
            async for chunk in jinshu_graph.astream(initial_state, config, stream_mode="updates"):
                # chunk 格式为 { "node_name": { "stream_events": [...], ... } }
                for node_name, updates in chunk.items():
                    if "stream_events" in updates:
                        for event in updates["stream_events"]:
                            # 若是审批挂起事件，附带 session_id (即 thread_id)，便于前端回传
                            if event.get("event") == "approval_required":
                                event["session_id"] = thread_id
                            yield event

            # 获取图当前步骤的最新状态，决定是否需要发送完成/汇总事件
            current_state = await jinshu_graph.aget_state(config)
            state_values = current_state.values if current_state else {}

            # 若图运行结束（不再处于 pending_approval 挂起状态），则发送最终的历史记录更新
            if state_values.get("pending_approval") is None:
                final_summary = state_values.get("final_summary", "")
                user_message = state_values.get("user_message", "")

                history_messages = [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": final_summary}
                ]
                yield {"event": "history_update", "messages": history_messages}

        except Exception as e:
            yield {"event": "error", "error": f"[LangGraph Engine Error] {str(e)}"}

    async def run_orchestration_stream(self, user_message: str) -> AsyncIterator[dict]:
        """与原 MultiAgentOrchestrator.run_orchestration_stream 兼容"""
        async for event in self.run_stream(user_message):
            yield event

    async def resume_orchestration_stream(self, session_id: str, approved: bool) -> AsyncIterator[dict]:
        """与原 MultiAgentOrchestrator.resume_orchestration_stream 兼容"""
        async for event in self.resume_stream(session_id, approved):
            yield event

    async def close(self):
        """释放编排总台资源"""
        pass
