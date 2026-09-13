"""Tab：面向单个标签页的高级封装（evaluate / 注入 JS 库 / 截图 / 文件注入 / 真实按键）。"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

import base64  # 截图 base64 解码
import json  # evaluate 参数序列化
from pathlib import Path  # 截图落盘路径类型
from typing import Any  # 通用类型标注

from .connection import CDPConnection, CDPError, CDPEvalError  # CDP 连接与异常族
from core.log import get_logger as _log  # 边界异常记录

from .jslib import call_expr, load_agent_js  # JS 源码加载器与调用表达式构造

# 真实按键映射：键名 → (可打印文本, key 名, Windows 虚拟键码)；供 real_press 使用
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
    """单标签页高级封装：evaluate / JS 库注入 / 截图 / 文件注入 / 真实按键。

    类职责：把 CDP 会话级操作收敛为页面语义方法，插件与业务层只面向本类。
    属性：conn 浏览器级连接；session_id 本页会话；target_info 页面 target 元数据；
        _lib_injected JS 库（window.__agent）是否已注入。
    生命周期：EdgeBrowser.attach_tab 构造 → 全程复用 → 随连接回收。
    """

    def __init__(self, conn: CDPConnection, session_id: str, target_info: dict):
        """Args: conn 浏览器级连接; session_id 本页会话; target_info 页面元数据。"""
        self.conn = conn  # 浏览器级连接
        self.session_id = session_id  # 本页 flat session
        self.target_info = target_info  # 页面 target 元数据
        self._lib_injected = False  # window.__agent 注入标记

    # ---- 基础 ----
    async def send(self, method: str, params: dict | None = None, timeout: float = 60.0) -> Any:
        """面向本页发送 CDP 请求。

        Globals Used: None。Calls: CDPConnection.send。
        Args: method 方法; params 参数; timeout 超时秒。Returns: 对端 result。
        """
        return await self.conn.send(method, params, session_id=self.session_id, timeout=timeout)

    async def enable(self) -> None:
        """启用 Runtime/Page/DOM 域（导航后重置注入标记）。

        Globals Used: None。Calls: send（三域）/ _log.debug。
        Args: None。Returns: None；单域失败仅记日志不阻断。
        """
        for m in ("Runtime.enable", "Page.enable", "DOM.enable"):
            try:
                await self.send(m)
            except CDPError as exc:  # noqa: BLE001 单域启用失败不阻断会话
                _log.debug("域启用失败 %s: %s", m, exc)
        self._lib_injected = False

    @property
    def url(self) -> str:
        """target 元数据里的页面地址（快照值）。Calls: 无。Args: None。Returns: str。"""
        return self.target_info.get("url", "")

    async def current_url(self) -> str:
        """页面实时地址（evaluate 失败回退 target 快照）。

        Globals Used: None。Calls: evaluate / url。
        Args: None。Returns: 当前 URL 字符串。
        """
        try:
            return await self.evaluate("location.href")
        except Exception:
            return self.url

    # ---- JS ----
    async def evaluate(self, expression: str, await_promise: bool = False, timeout: float = 60.0) -> Any:
        """在本页执行 JS 并返回值。

        Globals Used: None。Calls: send(Runtime.evaluate)；页内异常 raise CDPEvalError。
        Args: expression JS 表达式; await_promise 是否等待 Promise; timeout 超时秒。
        Returns: 页面值（returnByValue）。
        """
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
        """注入 window.__agent JS 库（幂等，导航后需重注）。

        Globals Used: None。Calls: evaluate(load_agent_js)。
        Args: None。Returns: None；失败 raise CDPError。
        """
        if self._lib_injected:
            return
        state = await self.evaluate(load_agent_js())
        self._lib_injected = state in ("ok", "already")
        if not self._lib_injected:
            raise CDPError("agent JS 库注入失败")

    async def agent(self, fn: str, *args: Any) -> Any:
        """调用 window.__agent.<fn>(...) 模拟用户操作。

        Globals Used: None。Calls: ensure_lib / evaluate / call_expr。
        Args: fn 库函数名; args 透传实参。Returns: 库函数返回值。
        """
        await self.ensure_lib()
        return await self.evaluate(call_expr(fn, *args))

    # ---- 导航 ----
    async def navigate(self, url: str, settle: float = 1.5, timeout: float = 30.0) -> dict:
        """导航到 URL 并等待渲染完成（含 SPA 缓冲）。

        Globals Used: None。Calls: send(Page.navigate) / evaluate。
        Args: url 目标地址; settle 渲染后缓冲秒; timeout 总超时秒。
        Returns: Page.navigate 响应 dict。
        """
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
        """轮询等待选择器出现。

        Globals Used: None。Calls: evaluate（querySelector 探测）。
        Args: selector CSS 选择器; timeout 超时秒。Returns: 是否出现。
        """
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
        """整页或元素截图（20s 快速失败）。

        Globals Used: None。Calls: evaluate（元素定位）/ send(Page.captureScreenshot)。
        Args: path 落盘路径（None 用默认目录）; selector 元素选择器（None 整页）。
        Returns: 落盘 Path；元素不可见 raise CDPError。
        """
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
        res = await self.send("Page.captureScreenshot", params, timeout=20)  # 快速失败：部分页面(如含滑块iframe)会挂起
        data = base64.b64decode(res["data"])
        if path is None:
            from core.config import PROJECT_ROOT

            path = PROJECT_ROOT / "screenshots" / "shot.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    # ---- 文件上传（纯 JS 做不到，必须走 CDP）----
    async def set_files(self, selector: str, file_paths: list[str | Path]) -> None:
        """把本地文件塞进页面 file input（纯 JS 做不到，必须走 CDP）。

        Globals Used: None。Calls: evaluate / send(DOM.requestNode, DOM.setFileInputFiles) / agent。
        Args: selector file input 选择器; file_paths 本地文件路径列表。
        Returns: None；input 缺失 raise CDPError。
        """
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
        """真实按键（isTrusted，合成事件不生效时的兜底）。

        Globals Used: _KEY_MAP（键名→虚拟键码）。Calls: send(Input.dispatchKeyEvent)。
        Args: key 键名（Enter/Tab/Escape/方向键等）。Returns: None。
        """
        text, key_name, vk = _KEY_MAP.get(key, ("", key, 0))
        for type_ in ("keyDown", "keyUp") if not text else (("keyDown", "char", "keyUp")):
            params: dict[str, Any] = {"type": type_, "key": key_name, "windowsVirtualKeyCode": vk}
            if type_ == "char":
                params["text"] = text
            await self.send("Input.dispatchKeyEvent", params)
