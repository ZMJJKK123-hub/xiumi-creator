"""CDP 浏览器级 WebSocket 连接（flat session 模式）。

一条浏览器级连接即可操作所有标签页：Target.attachToTarget(flatten=True)
拿到 sessionId 后，send() 携带 sessionId 即面向该标签页。
"""
from __future__ import annotations

import asyncio
import itertools
import json
import urllib.request
from typing import Any, Callable

import websockets

DEFAULT_TIMEOUT = 60.0


class CDPError(RuntimeError):
    pass


class CDPProtocolError(CDPError):
    """CDP 返回了 error 结果。"""

    def __init__(self, method: str, code: int, message: str):
        super().__init__(f"CDP {method} 失败 [{code}]: {message}")
        self.method, self.code, self.message = method, code, message


class CDPEvalError(CDPError):
    """页面内 JS 抛出异常。"""

    def __init__(self, expression: str, detail: str):
        super().__init__(f"JS 执行出错: {detail}\n--- 表达式 ---\n{expression[:500]}")
        self.detail = detail


EventCallback = Callable[[str | None, str, dict], None]


class CDPConnection:
    def __init__(self, ws_url: str, port: int):
        self._ws_url = ws_url
        self.port = port
        self._ws: websockets.WebSocketCommonProtocol | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._event_cbs: list[EventCallback] = []
        self._recv_task: asyncio.Task | None = None
        self._closed = False

    # ---- 生命周期 ----
    @classmethod
    async def connect(cls, port: int, timeout: float = 15.0) -> "CDPConnection":
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
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))

    async def _open(self) -> None:
        self._ws = await websockets.connect(self._ws_url, max_size=64 * 1024 * 1024, ping_interval=20)
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def close(self) -> None:
        self._closed = True
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws:
            await self._ws.close()

    def http_get(self, path: str) -> dict:
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
        """callback(session_id, method, params) —— 同步回调。"""
        self._event_cbs.append(callback)

    async def _recv_loop(self) -> None:
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
                        except Exception:
                            pass
        except asyncio.CancelledError:
            pass
        except Exception:
            if not self._closed:
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(CDPError("CDP 连接断开"))

    # ---- Target 管理 ----
    async def list_pages(self) -> list[dict]:
        res = await self.send("Target.getTargets")
        return [t for t in res.get("targetInfos", []) if t.get("type") == "page"]

    async def new_tab(self, url: str = "about:blank") -> dict:
        res = await self.send("Target.createTarget", {"url": url})
        tid = res["targetId"]
        for t in await self.list_pages():
            if t["targetId"] == tid:
                return t
        return {"targetId": tid, "url": url}

    async def attach(self, target_id: str) -> str:
        res = await self.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        return res["sessionId"]
