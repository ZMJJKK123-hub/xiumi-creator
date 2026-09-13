"""CDP 浏览器级 WebSocket 连接（flat session 模式）。

一条浏览器级连接即可操作所有标签页：Target.attachToTarget(flatten=True)
拿到 sessionId 后，send() 携带 sessionId 即面向该标签页。
"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

import asyncio  # 收发循环与超时控制
import itertools  # 消息 id 自增计数器
import json  # CDP 消息序列化
import urllib.request  # /json/version 等 HTTP 探测
from typing import Any, Callable  # 通用类型与回调签名

import websockets  # CDP WebSocket 客户端

from core.log import get_logger as _log  # 边界异常记录

DEFAULT_TIMEOUT = 60.0  # CDP 单次请求默认超时（秒）


class CDPError(RuntimeError):
    """CDP 层错误基类。

    类职责：统一本层可预期异常的根类型，供上层 except CDPError 一网打尽。
    属性：无附加（子类各自扩展）。
    生命周期：raise 即弃，不持有资源。
    """

    pass


class CDPProtocolError(CDPError):
    """CDP 协议层错误：对端返回 error 响应。

    类职责：包装 CDP error 响应为带上下文（方法名/错误码）的异常。
    属性：method 出错方法；code 协议错误码；message 对端原始消息。
    生命周期：send() 解析响应时 raise，调用方捕获或上抛。
    """

    def __init__(self, method: str, code: int, message: str):
        """Args: method CDP 方法名; code 错误码; message 对端消息。"""
        super().__init__(f"CDP {method} 失败 [{code}]: {message}")
        self.method, self.code, self.message = method, code, message


class CDPEvalError(CDPError):
    """页面执行层错误：注入的 JS 抛出异常。

    类职责：携带出错表达式与页内异常详情，便于排查选择器/脚本问题。
    属性：detail 页内异常文本。
    生命周期：evaluate() 解析 exceptionDetails 时 raise。
    """

    def __init__(self, expression: str, detail: str):
        """Args: expression 出错 JS; detail 页内异常详情。"""
        super().__init__(f"JS 执行出错: {detail}\n--- 表达式 ---\n{expression[:500]}")
        self.detail = detail


EventCallback = Callable[[str | None, str, dict], None]


class CDPConnection:
    """浏览器级 CDP WebSocket 连接（flat session 模式）。

    类职责：持有唯一浏览器级连接，收发 CDP 消息、分发事件、管理标签页 target。
    属性：_ws_url 浏览器 ws 地址；port 调试端口；_ws WebSocket 连接；
        _ids 消息 id 计数器；_pending id→Future 响应表；_event_cbs 事件订阅者；
        _recv_task 收发循环任务；_closed 关闭标记。
    生命周期：connect() 工厂创建 → send/on_event 全程复用 → close() 回收。
    """

    def __init__(self, ws_url: str, port: int):
        """Args: ws_url 浏览器级 ws 地址; port 调试端口。"""
        self._ws_url = ws_url  # 浏览器级 ws 地址
        self.port = port  # HTTP/WS 调试端口
        self._ws: websockets.WebSocketCommonProtocol | None = None  # WebSocket 连接
        self._ids = itertools.count(1)  # 出站消息 id 计数器
        self._pending: dict[int, asyncio.Future] = {}  # id→响应 Future 表
        self._event_cbs: list[EventCallback] = []  # 事件订阅回调
        self._recv_task: asyncio.Task | None = None  # 收发循环任务
        self._closed = False  # 主动关闭标记

    # ---- 生命周期 ----
    @classmethod
    async def connect(cls, port: int, timeout: float = 15.0) -> "CDPConnection":
        """连接到调试端口的浏览器级端点。

        Globals Used: None。Calls: _http_get / _open。
        Args: port 调试端口; timeout HTTP 探测超时秒。Returns: 已就绪连接实例。
        """
        version = await asyncio.wait_for(
            asyncio.to_thread(cls._http_get, port, "/json/version"), timeout=timeout
        )
        ws_url = version.get("webSocketDebuggerUrl")
        if not ws_url:
            raise CDPError("未能从 /json/version 获取 webSocketDebuggerUrl")
        self = cls(ws_url, port)
        await self._open()
        return self

    @staticmethod
    def _http_get(port: int, path: str) -> dict:
        """同步 HTTP GET 调试端点（线程池中调用）。

        Args: port 端口; path 路径。Returns: 解析后的 JSON dict。
        """
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))

    async def _open(self) -> None:
        """建立 WebSocket 并启动收发循环。Args: None。Returns: None。"""
        self._ws = await websockets.connect(self._ws_url, max_size=64 * 1024 * 1024, ping_interval=20)
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def close(self) -> None:
        """关闭连接：停收发循环并断开 WebSocket。

        Globals Used: None。Calls: _recv_task.cancel / ws.close。
        Args: None。Returns: None。
        """
        self._closed = True
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws:
            await self._ws.close()

    def http_get(self, path: str) -> dict:
        """实例口径的调试端点 GET。

        Calls: _http_get。Args: path 路径（如 /json/list）。Returns: JSON dict。
        """
        return self._http_get(self.port, path)

    # ---- 消息收发 ----
    async def send(
        self,
        method: str,
        params: dict | None = None,
        *,
        session_id: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Any:
        """发送 CDP 请求并等待响应。

        Globals Used: DEFAULT_TIMEOUT（默认超时）。Calls: ws.send / _recv_loop（经 Future 汇合）。
        Args: method CDP 方法; params 参数; session_id 标签页会话; timeout 超时秒。
        Returns: 对端 result 对象；失败 raise CDPProtocolError/CDPError。
        """
        if not self._ws:
            raise CDPError("CDP 连接未打开")
        mid = next(self._ids)
        msg: dict[str, Any] = {"id": mid, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        try:
            await self._ws.send(json.dumps(msg))
            result = await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(mid, None)
        return result

    def on_event(self, callback: EventCallback) -> None:
        """订阅 CDP 事件。

        Globals Used: None。Calls: 无（登记回调）。
        Args: callback 形如 (session_id, method, params) 的同步回调。Returns: None。
        """
        self._event_cbs.append(callback)

    async def _recv_loop(self) -> None:
        """常驻收发循环：响应 Future 汇合 + 事件分发。

        Args: None。Returns: None（连接断开即退出并唤醒挂起请求）。
        """
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._pending.get(msg["id"])
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(
                                CDPProtocolError(msg.get("method", "?"), msg["error"].get("code", -1), msg["error"].get("message", ""))
                            )
                        else:
                            fut.set_result(msg.get("result"))
                else:
                    sid = msg.get("sessionId")
                    method = msg.get("method", "")
                    params = msg.get("params") or {}
                    for cb in list(self._event_cbs):
                        try:
                            cb(sid, method, params)
                        except Exception as exc:  # noqa: BLE001 单回调失败不阻断事件流
                            _log.debug("事件回调失败 %s: %s", method, exc)
        except asyncio.CancelledError:
            pass
        except Exception:
            if not self._closed:
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(CDPError("CDP 连接断开"))

    # ---- Target 管理 ----
    async def list_pages(self) -> list[dict]:
        """列出全部页面型 target。

        Globals Used: None。Calls: send(Target.getTargets)。
        Args: None。Returns: targetInfo dict 列表。
        """
        res = await self.send("Target.getTargets")
        return [t for t in res.get("targetInfos", []) if t.get("type") == "page"]

    async def new_tab(self, url: str = "about:blank") -> dict:
        """新建标签页并返回其 targetInfo。

        Globals Used: None。Calls: send(Target.createTarget) / list_pages。
        Args: url 初始地址。Returns: 新标签页 targetInfo。
        """
        res = await self.send("Target.createTarget", {"url": url})
        tid = res["targetId"]
        for t in await self.list_pages():
            if t["targetId"] == tid:
                return t
        return {"targetId": tid, "url": url}

    async def attach(self, target_id: str) -> str:
        """附加到 target 得到 flat session（send 可携带的 sessionId）。

        Globals Used: None。Calls: send(Target.attachToTarget)。
        Args: target_id 目标标签页。Returns: sessionId 字符串。
        """
        res = await self.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        return res["sessionId"]
