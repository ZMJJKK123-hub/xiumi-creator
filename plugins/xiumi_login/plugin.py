"""xiumi_login 插件：登录态检查。

登录由用户在浏览器窗口自行完成（滑块/扫码均可），
/login 命令只负责弹出官网、轮询检测、回报结果。
"""
from __future__ import annotations

import asyncio  # 轮询间隔与超时
import json  # 选择器转义

from cdp.helpers import Tab  # 页面标签类型
from core.events import Event, EventType  # 状态提示事件
from core.log import get_logger  # 边界异常记录
from core.registry import AppContext, Plugin, Tool  # 插件契约

from pathlib import Path  # 选择器文件定位

_logger = get_logger(__name__)
_HERE = Path(__file__).parent

# 登录判定等待页面渲染的最长秒数
_RENDER_TIMEOUT = 8.0


def _selectors() -> dict:
    """读取登录相关选择器。Args: None。Returns: dict。"""
    return json.loads((_HERE / "selectors.json").read_text(encoding="utf-8"))


async def _wait_rendered(tab: Tab, timeout: float = _RENDER_TIMEOUT) -> bool:
    """等 SPA 渲染出实际内容（body 文本 > 30 字符），防空白页误判。

    Args: tab 页面标签; timeout 最长等待秒。Returns: 是否渲染完成。
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            n = await tab.evaluate("(document.body && document.body.innerText || '').trim().length")
        except Exception as exc:  # noqa: BLE001 页面跳转期评估失败
            n = 0
            _logger.debug("等渲染: %s", exc)
        if n and int(n) > 30:
            return True
        await asyncio.sleep(0.4)
    return False


async def check_login(ctx: AppContext, navigate: bool = True) -> bool:
    """登录态检查：/auth 子页直接判未登录，其余等渲染后按文本启发式。

    Args: ctx 上下文; navigate 是否先导航到首页。Returns: 是否已登录。
    """
    tab = ctx.require_tab()
    sel = _selectors()
    url = await tab.current_url()
    if navigate and "xiumi.us" not in url:
        await tab.navigate(sel["home_url"])
        url = await tab.current_url()
    if "xiumi.us" not in url:
        return False
    if "/auth" in url:  # 登录页=未登录铁证（登录成功会跳走）
        ctx.state["xiumi_logged_in"] = False
        return False
    if not await _wait_rendered(tab):
        ctx.state["xiumi_logged_in"] = False
        return False
    if sel.get("check_js"):
        logged_in = bool(await tab.evaluate(sel["check_js"]))
    else:
        res = await tab.evaluate(
            r"(function(){var t=(document.body.innerText||'').slice(0,3000);"
            r"return /登\s*录|立即登录/.test(t);})()"
        )
        logged_in = not res
    ctx.state["xiumi_logged_in"] = logged_in
    return logged_in


async def _tool_login_check(ctx: AppContext, args: dict) -> str:
    """xiumi_login_check 处理器。Args: ctx; args 空。Returns: 状态文本。"""
    ok = await check_login(ctx)
    return "已登录" if ok else "未登录，请提示用户输入 /login 命令完成登录"


class XiumiLoginPlugin(Plugin):
    """登录检查插件：登录动作本身由 /login 命令与用户协作完成。"""

    name = "xiumi_login"
    description = "秀米登录态检查工具；登录由用户在浏览器完成"

    def actions(self, ctx: AppContext) -> dict:
        """暴露登录态检查动作。Args: ctx。Returns: 动作表。"""
        return {"xiumi_login.check": lambda: check_login(ctx)}

    def tools(self, ctx: AppContext) -> list[Tool]:
        """注册登录检查工具。Args: ctx。Returns: 工具列表。"""
        return [
            Tool(
                name="xiumi_login_check",
                description="检查当前是否已登录秀米，返回 已登录/未登录",
                parameters={"type": "object", "properties": {}},
                handler=_tool_login_check,
            )
        ]
