"""轻量异步事件总线：TUI、Agent、插件之间的唯一通信通道。

事件约定（type, data）:
  status        {text}                    启动/就绪等状态提示
  chat          {role, text}              用户/助手消息（进入聊天面板）
  action        {name, args}              工具调用开始（进入动作面板）
  tool_result   {name, result}            工具调用结束
  screenshot    {path}                    产生截图文件
  sms_required  {}                        账密登录遇验证码，需要用户补输
  login_result  {ok, message}             登录轮询结果
  task_done     {ok, message}             一轮任务结束
  error         {message}                 错误提示
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

Handler = Callable[[str, dict[str, Any]], "None | Awaitable[None]"]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = {}

    def on(self, event_type: str, handler: Handler) -> None:
        self._subs.setdefault(event_type, []).append(handler)

    def off(self, event_type: str, handler: Handler) -> None:
        try:
            self._subs.get(event_type, []).remove(handler)
        except ValueError:
            pass

    async def emit(self, event_type: str, **data: Any) -> None:
        handlers = list(self._subs.get(event_type, [])) + list(self._subs.get("*", []))
        for fn in handlers:
            try:
                res = fn(event_type, data)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                # 单个订阅者异常不影响其他订阅者与发送方
                continue
