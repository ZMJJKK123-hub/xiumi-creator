"""Tab：面向单个标签页的高级封装（evaluate / 注入 JS 库 / 截图 / 文件注入 / 真实按键）。"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from .connection import CDPConnection, CDPError, CDPEvalError
from core.log import get_logger as _log  # 边界异常记录

from .jslib import call_expr, load_agent_js  # JS 源码加载器与调用表达式构造

_KEY_MAP = {
    "Enter": ("\r", "Enter", 13),
    "Tab": ("\t", "Tab", 9),
    "Escape": ("", "Escape", 27),
    "Backspace": ("\b", "Backspace", 8),
    "Delete": ("", "Delete", 46),
    "ArrowLeft": ("", "Left", 37),
    "ArrowRight": ("", "Right", 39),
    "ArrowUp": ("", "Up", 38),
    "ArrowDown": ("", "Down", 40),
}


class Tab:
    def __init__(self, conn: CDPConnection, session_id: str, target_info: dict):
        self.conn = conn
        self.session_id = session_id
        self.target_info = target_info
        self._lib_injected = False

    # ---- 基础 ----
    async def send(self, method: str, params: dict | None = None, timeout: float = 60.0) -> Any:
        return await self.conn.send(method, params, session_id=self.session_id, timeout=timeout)

    async def enable(self) -> None:
        for m in ("Runtime.enable", "Page.enable", "DOM.enable"):
            try:
                await self.send(m)
            except CDPError as exc:  # noqa: BLE001 单域启用失败不阻断会话
                _log.debug("域启用失败 %s: %s", m, exc)
        self._lib_injected = False

    @property
    def url(self) -> str:
        return self.target_info.get("url", "")

    async def current_url(self) -> str:
        try:
            return await self.evaluate("location.href")
        except Exception:
            return self.url

    # ---- JS ----
    async def evaluate(self, expression: str, await_promise: bool = False, timeout: float = 60.0) -> Any:
        res = await self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
                "userGesture": True,
            },
            timeout=timeout,
        )
        if res.get("exceptionDetails"):
            d = res["exceptionDetails"]
            detail = d.get("exception", {}).get("description") or d.get("text", "unknown")
            raise CDPEvalError(expression, detail)
        result = res.get("result", {})
        return result.get("value")

    async def ensure_lib(self) -> None:
        if self._lib_injected:
            return
        state = await self.evaluate(load_agent_js())
        self._lib_injected = state in ("ok", "already")
        if not self._lib_injected:
            raise CDPError("agent JS 库注入失败")

    async def agent(self, fn: str, *args: Any) -> Any:
        """调用 window.__agent.fn(...)，返回 JSON 可序列化结果。"""
        await self.ensure_lib()
        return await self.evaluate(call_expr(fn, *args))

    # ---- 导航 ----
    async def navigate(self, url: str, settle: float = 1.5, timeout: float = 30.0) -> dict:
        self._lib_injected = False
        res = await self.send("Page.navigate", {"url": url}, timeout=timeout)
        import asyncio

        await asyncio.sleep(0.3)
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            state = await self.evaluate("document.readyState")
            if state == "complete":
                break
            await asyncio.sleep(0.3)
        await asyncio.sleep(settle)  # SPA 渲染缓冲
        self.target_info["url"] = url
        return res

    async def wait_selector(self, selector: str, timeout: float = 10.0) -> bool:
        import asyncio

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            found = await self.evaluate(f"!!document.querySelector({json.dumps(selector)})")
            if found:
                return True
            await asyncio.sleep(0.4)
        return False

    # ---- 截图 ----
    async def screenshot(self, path: Path | None = None, selector: str | None = None) -> Path:
        params: dict[str, Any] = {"format": "png"}
        if selector:
            rect = await self.evaluate(
                f"(() => {{ const el = document.querySelector({json.dumps(selector)});"
                f" if (!el) return null; const r = el.getBoundingClientRect();"
                f" return {{x: r.x, y: r.y + window.scrollY, width: r.width, height: r.height}}; }})()"
            )
            if not rect or rect["width"] < 2:
                raise CDPError(f"截图失败：找不到可见元素 {selector}")
            params["clip"] = {**rect, "scale": 1}
            params["captureBeyondViewport"] = True
        res = await self.send("Page.captureScreenshot", params, timeout=60)
        data = base64.b64decode(res["data"])
        if path is None:
            from core.config import PROJECT_ROOT

            path = PROJECT_ROOT / "screenshots" / "shot.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    # ---- 文件上传（纯 JS 做不到，必须走 CDP）----
    async def set_files(self, selector: str, file_paths: list[str | Path]) -> None:
        """把本地文件塞进页面 file input（如秀米图库上传）。"""
        # 先确保 input 存在
        exists = await self.evaluate(f"!!document.querySelector({json.dumps(selector)})")
        if not exists:
            raise CDPError(f"file input 不存在: {selector}")
        res = await self.send(
            "Runtime.evaluate",
            {
                "expression": f"document.querySelector({json.dumps(selector)})",
                "returnByValue": False,
            },
        )
        object_id = res.get("result", {}).get("objectId")
        if not object_id:
            raise CDPError("无法获取 file input 的 objectId")
        node = await self.send("DOM.requestNode", {"objectId": object_id})
        abs_paths = [str(Path(p).resolve()) for p in file_paths]
        for p in abs_paths:
            if not Path(p).exists():
                raise CDPError(f"文件不存在: {p}")
        await self.send("DOM.setFileInputFiles", {"files": abs_paths, "nodeId": node["nodeId"]})
        # 通知框架文件已选择
        await self.agent("triggerChange", selector)

    # ---- 真实按键兜底（isTrusted，合成事件不生效时用）----
    async def real_press(self, key: str) -> None:
        text, key_name, vk = _KEY_MAP.get(key, ("", key, 0))
        for type_ in ("keyDown", "keyUp") if not text else (("keyDown", "char", "keyUp")):
            params: dict[str, Any] = {"type": type_, "key": key_name, "windowsVirtualKeyCode": vk}
            if type_ == "char":
                params["text"] = text
            await self.send("Input.dispatchKeyEvent", params)

    async def real_type(self, text: str) -> None:
        """逐字符发送真实键盘输入（焦点必须在目标输入框上）。"""
        for ch in text:
            await self.send("Input.dispatchKeyEvent", {"type": "char", "text": ch})
