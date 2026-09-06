"""Agent 主循环：LLM function calling → 插件工具执行 → 结果回填。"""
from __future__ import annotations

import json
import time

from core.events import EventBus
from core.llm import LLMClient
from core.prompts import SYSTEM_PROMPT
from core.registry import AppContext, ToolRegistry


class Agent:
    def __init__(self, ctx: AppContext, registry: ToolRegistry, llm: LLMClient, bus: EventBus):
        self.ctx = ctx
        self.registry = registry
        self.llm = llm
        self.bus = bus

    async def run(self, task: str) -> None:
        """执行一轮用户任务。过程事件全部发到事件总线，由 TUI 呈现。"""
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        started = time.time()
        tool_calls_total = 0

        for step in range(self.ctx.config.max_steps):
            reply = await self.llm.chat(messages, self.registry.schemas())
            if reply.get("content"):
                await self.bus.emit("chat", role="assistant", text=reply["content"])
            if not reply.get("tool_calls"):
                await self.bus.emit("task_done", ok=True, message=f"共 {tool_calls_total} 次工具调用，用时 {time.time()-started:.0f}s")
                return

            messages.append(reply)
            for tc in reply["tool_calls"]:
                fn = tc["function"]
                try:
                    args = json.loads(fn["arguments"] or "{}")
                except json.JSONDecodeError as e:
                    args = {}
                    result = f"ERROR: 工具参数不是合法 JSON: {e}"
                else:
                    await self.bus.emit("action", name=fn["name"], args=args)
                    tool_calls_total += 1
                    try:
                        result = await self.registry.call(self.ctx, fn["name"], args)
                    except Exception as e:  # 工具异常回填给 LLM 自行恢复
                        result = f"ERROR: {type(e).__name__}: {e}"
                    await self.bus.emit("tool_result", name=fn["name"], result=result)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

        await self.bus.emit(
            "task_done",
            ok=False,
            message=f"已达最大步数 {self.ctx.config.max_steps}，任务中断。请缩小任务范围后重试。",
        )
