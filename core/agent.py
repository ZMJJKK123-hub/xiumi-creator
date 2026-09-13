"""Agent 主循环：LLM function calling → 插件工具执行 → 结果回填。"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

import json  # 工具参数 JSON 解析与结果序列化
import time  # 任务计时

from core.events import Event, EventBus, EventType  # 强类型事件总线
from core.llm import LLMClient  # OpenAI 兼容客户端
from core.prompts import SYSTEM_PROMPT  # 系统提示词（秀米 SOP + 排版规范）
from core.registry import AppContext, ToolRegistry  # 上下文与工具注册表


class Agent:
    """任务执行 Agent。

    类职责：驱动 LLM 与工具的多轮循环，过程事件发到总线由 TUI 呈现。
    属性：ctx 全局上下文；registry 工具注册表；llm 客户端；bus 事件总线。
    生命周期：boot 构造 → 每个任务 run() 一轮 → 随 App 回收。
    """

    def __init__(self, ctx: AppContext, registry: ToolRegistry, llm: LLMClient, bus: EventBus) -> None:
        """注入协作对象。

        Args: ctx 上下文; registry 工具表; llm 客户端; bus 事件总线。
        """
        self.ctx = ctx
        self.registry = registry
        self.llm = llm
        self.bus = bus

    async def run(self, task: str, sink=None) -> None:
        """执行一轮用户任务（LLM 思考增量经 sink 实时外送）。

        Globals Used: SYSTEM_PROMPT（模块级系统提示词）。
        Calls: LLMClient.chat_stream / _exec_tool_calls / bus.emit。
        Args: task 用户任务文本; sink 可选思考回调对象
            （round_start/reasoning/content/round_done 四方法）。Returns: None。
        """
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        started = time.time()
        tool_calls_total = 0

        for _step in range(self.ctx.config.max_steps):
            reply = await self._llm_round(messages, sink)
            if reply.get("content"):
                await self.bus.emit(Event(EventType.CHAT, role="assistant", text=reply["content"]))
            if not reply.get("tool_calls"):
                await self.bus.emit(
                    Event(
                        EventType.TASK_DONE,
                        ok=True,
                        message=f"共 {tool_calls_total} 次工具调用，用时 {time.time() - started:.0f}s",
                    )
                )
                return
            messages.append(reply)
            tool_calls_total += await self._exec_tool_calls(messages, reply["tool_calls"])

        await self.bus.emit(
            Event(
                EventType.TASK_DONE,
                ok=False,
                message=f"已达最大步数 {self.ctx.config.max_steps}，任务中断。请缩小任务范围后重试。",
            )
        )

    async def _llm_round(self, messages: list[dict], sink) -> dict:
        """单轮 LLM 调用：通知 sink 起止，思考增量透传。

        Args: messages 对话历史（就地追加）; sink 思考回调对象或 None。
        Returns: 标准化回复 dict。
        """
        if sink is None:
            return await self.llm.chat_stream(messages, self.registry.schemas())
        sink.round_start()
        try:
            return await self.llm.chat_stream(
                messages, self.registry.schemas(),
                on_reasoning=sink.reasoning, on_content=sink.content,
            )
        finally:
            sink.round_done()

    async def _exec_tool_calls(self, messages: list, tool_calls: list) -> int:
        """执行一批工具调用并回填结果消息。

        Args: messages 对话消息（就地追加 tool 消息）; tool_calls 本轮调用。
        Returns: 成功分发的调用数。
        """
        done = 0
        for tc in tool_calls:
            fn = tc["function"]
            try:
                args = json.loads(fn["arguments"] or "{}")
            except json.JSONDecodeError as e:
                args, result = {}, f"ERROR: 工具参数不是合法 JSON: {e}"
            else:
                await self.bus.emit(Event(EventType.ACTION, name=fn["name"], args=args))
                done += 1
                try:
                    result = await self.registry.call(self.ctx, fn["name"], args)
                except Exception as e:  # noqa: BLE001 工具异常回填给 LLM 自行恢复
                    result = f"ERROR: {type(e).__name__}: {e}"
                await self.bus.emit(Event(EventType.TOOL_RESULT, name=fn["name"], result=result))
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
        return done
