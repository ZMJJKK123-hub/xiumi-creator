"""强类型事件总线：业务层到表现层的唯一回流通道（架构解耦的关键件）。

架构定位：core 业务层；发布方 agent.py/插件 handler，订阅方几乎只有
tui/app._wire_events（一处接线，全类事件落流水）。上行用事件、下行用
方法调用——TUI 永远不轮询业务层。新增事件=EventType 加成员+Event 加字段。


Rule2 §4 契约优先：事件以 Event dataclass 传递，禁止裸 dict/裸 kwargs；
订阅端按 EventType 分发，载荷字段在类定义中显式声明。
"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

import asyncio  # iscoroutine 判断，支持异步/同步订阅者混合分发
from dataclasses import dataclass, field  # dataclass 构建事件 DTO；field 提供容器默认值
from enum import Enum  # 枚举约束合法事件集合
from typing import Awaitable, Callable  # 订阅者回调类型标注

from core.log import get_logger  # 统一 logger，记录订阅者异常（替代静默吞掉）

# 模块 logger：本文件内仅用于订阅者异常与重复退订记录
_logger = get_logger(__name__)


class EventType(Enum):
    """事件类型枚举：全系统合法事件的封闭集合。

    类职责：强类型事件路由键，杜绝魔法字符串。
    属性：各成员即事件种类（值用于日志）。
    生命周期：Event 构造时取用，随 Event 废弃。
    """

    CHAT = "chat"                      # 对话消息 {role, text}
    ACTION = "action"                  # 工具调用开始 {name, args}
    TOOL_RESULT = "tool_result"        # 工具调用结束 {name, result}
    SCREENSHOT = "screenshot"          # 产生截图文件 {path}
    TASK_DONE = "task_done"            # 一轮任务结束 {ok, message}
    ERROR = "error"                    # 错误提示 {message}


@dataclass
class Event:
    """事件 DTO：类型枚举 + 强类型载荷字段（按事件类型取用，默认空值）。

    类职责：单一强类型载体，跨层传递事件载荷。
    属性：type 分发键；text/role CHAT 用；
    name/args/result ACTION 与 TOOL_RESULT 用；path SCREENSHOT 用；
    ok/message TASK_DONE 用。
    生命周期：emit() 构造 → 总线同步分发全部订阅者 → 废弃。
    """

    type: EventType
    text: str = ""
    role: str = ""
    name: str = ""
    args: dict = field(default_factory=dict)
    result: str = ""
    path: str = ""
    ok: bool = False
    message: str = ""


# 订阅者签名：接收 Event，返回 None 或可等待协程
Handler = Callable[[Event], "None | Awaitable[None]"]


class EventBus:
    """进程内异步事件总线：发布/订阅 + 同步异步混合分发。

    职责：解耦 TUI 呈现层与 Agent/插件事件源。
    属性：_subs 按 EventType 分组的订阅者列表。
    生命周期：App 构造时创建，随进程回收；订阅者异常记录后继续分发。
    """

    def __init__(self) -> None:
        self._subs: dict[EventType, list[Handler]] = {}

    def on(self, event_type: EventType, handler: Handler) -> None:
        """订阅指定事件。

        Globals Used: None。Calls: dict.setdefault。
        Args: event_type 目标事件；handler 同步或异步回调。
        Returns: None。
        """
        self._subs.setdefault(event_type, []).append(handler)

    def off(self, event_type: EventType, handler: Handler) -> None:
        """退订；未注册时仅记 DEBUG（屏卸载允许重复退订）。

        Globals Used: None。Calls: list.remove。
        Args: event_type 目标事件；handler 回调。Returns: None。
        """
        try:
            self._subs.get(event_type, []).remove(handler)
        except ValueError:
            _logger.debug("退订了未注册的处理器: %s", event_type.value)

    async def emit(self, event: Event) -> None:
        """向全部订阅者分发事件。

        Globals Used: None。Calls: asyncio.iscoroutine。
        Args: event 强类型事件。Returns: None。
        单个订阅者异常记 ERROR（含堆栈）后继续分发，隔离边界故障。
        """
        for fn in list(self._subs.get(event.type, [])):
            try:
                res = fn(event)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:  # noqa: BLE001 订阅者边界必须隔离
                _logger.error("事件订阅者异常 %s: %s", event.type.value, exc, exc_info=True)
