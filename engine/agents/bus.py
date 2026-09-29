"""
金枢 2.0 (Jin-Shu OS) - Asynchronous Event Message Bus (异步事件消息总线)
========================================================================
实现去中心化的发布/订阅 (Pub/Sub) 机制。智能体之间不再通过直接函数传参耦合，
而是将推演结论与工具调用封装为异步事件发布到总线，由订阅方按需拉取，彻底解决并发锁死与上下文雪崩。
"""

import asyncio
import time
from typing import Dict, Any, List, Callable, Awaitable
from dataclasses import dataclass, field


@dataclass
class AgentEvent:
    """异步智能体通信事件封装"""
    event_id: str
    source_agent: str
    event_type: str             # 如 'EVIDENCE_POST', 'TOOL_CALL', 'APPROVAL_REQ', 'STATE_CHANGE'
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class AgentMessageBus:
    """去中心化异步消息总线"""

    def __init__(self):
        self.subscribers: Dict[str, List[Callable[[AgentEvent], Awaitable[None]]]] = {}
        self.event_history: List[AgentEvent] = []
        self._queue: asyncio.Queue = None
        self._running: bool = False
        self._worker_task: asyncio.Task = None

    def subscribe(self, event_type: str, handler: Callable[[AgentEvent], Awaitable[None]]):
        """订阅特定类型的事件"""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(handler)

    async def publish(self, event: AgentEvent):
        """发布异步事件到总线队列"""
        self.event_history.append(event)
        if self._queue:
            await self._queue.put(event)

    async def start(self):
        """启动后台事件分发引擎（绑定到当前活动事件循环）"""
        self._queue = asyncio.Queue()
        self._running = True
        self._worker_task = asyncio.create_task(self._dispatch_loop())

    async def stop(self):
        """停止事件分发引擎"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass


    async def _dispatch_loop(self):
        """后台异步分发循环"""
        while self._running:
            try:
                event: AgentEvent = await self._queue.get()
                handlers = self.subscribers.get(event.event_type, [])
                for h in handlers:
                    try:
                        await h(event)
                    except Exception as e:
                        print(f"[Bus Dispatch Error]: {e}")
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Bus Fatal Error]: {e}")


# 全局单例异步消息总线
global_message_bus = AgentMessageBus()
