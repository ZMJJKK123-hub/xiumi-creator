"""xiumi_login 插件：登录态检查 + 账密登录（供 TUI 直接调用，凭据不经过 LLM）。

- 动作 xiumi_login.password  账密登录：TUI 模态框收集账号密码 → 后台代填页面（含协议勾选）→ 提交；
                               出现滑块验证码时浏览器窗口自动弹出供人工完成（发 captcha_required 事件），
                               短信验证码在 TUI 补输（sms_required 事件）
- 工具 xiumi_login_check     供 LLM 查询登录态（只读）

选择器已实地踩点确认（见同目录 selectors.json）。二维码登录已按需求移除。
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from cdp.helpers import Tab
from core.events import Event, EventType  # 强类型事件
from core.log import get_logger  # 分步函数的边界异常记录  # 强类型事件
from core.registry import AppContext, Plugin, Tool

HERE = Path(__file__).parent


def _selectors() -> dict:
    return json.loads((HERE / "selectors.json").read_text(encoding="utf-8"))


async def _wait_rendered(tab, timeout: float = 8.0) -> bool:
    """等 SPA 渲染出实际内容（body 文本 > 30 字符）。

    在空白/加载中的页面上跑登录启发式会把空文本误判为「已登录」，
    必须先等到页面真正渲染。
    """
    import asyncio

    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            n = await tab.evaluate("(document.body && document.body.innerText || '').trim().length")
        except Exception:
            n = 0
        if n and int(n) > 30:
            return True
        await asyncio.sleep(0.4)
    return False


async def check_login(ctx: AppContext, navigate: bool = True) -> bool:
    """登录态检查：先等页面渲染，再按启发式判断（check_js 优先）。

    页面始终渲染不出来时按「未登录」处理（安全默认，会弹登录窗）。
    """
    tab = ctx.require_tab()
    sel = _selectors()
    url = await tab.current_url()
    if navigate and "xiumi.us" not in url:
        await tab.navigate(sel["home_url"])
        url = await tab.current_url()
    if "xiumi.us" not in url:
        return False
    # 停在 /auth 任何子页 = 未登录的铁证（登录成功会跳走）；
    # 其子页（如 auth/email/login 验证码页）按钮是「获取验证码」而非「登录」，
    # 文本启发式在那里会误判为已登录
    if "/auth" in url:
        ctx.state["xiumi_logged_in"] = False
        return False
    if not await _wait_rendered(tab):
        ctx.state["xiumi_logged_in"] = False
        return False
    if sel.get("check_js"):
        logged_in = bool(await tab.evaluate(sel["check_js"]))
    else:
        # 启发式：未登录时页面显著位置有「登录」字样（首页/登录页标题都会出现）
        res = await tab.evaluate(
            r"(function(){var t=(document.body.innerText||'').slice(0,3000);"
            r"return /登\s*录|立即登录/.test(t);})()"
        )
        logged_in = not res
    ctx.state["xiumi_logged_in"] = logged_in
    return logged_in


async def _wait_login(ctx: AppContext, timeout: float) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            if await check_login(ctx, navigate=False):
                return True
        except Exception:
            pass  # 页面正在跳转时 evaluate 可能失败，继续轮询
        await asyncio.sleep(2.0)
    return False


async def _fill_input(tab: Tab, css: str, value: str, label: str, timeout: float = 15.0) -> None:
    """等待输入框渲染出现（SPA 异步渲染）后点击并填值。

    Args: tab 页面标签; css 选择器; value 填入值; label 中文名（报错用）; timeout 最长等待秒。
    Raises: RuntimeError 超时未找到。
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        found = await tab.agent("find", css, 5)
        if found:
            await tab.agent("click", found[0]["ref"])
            await tab.agent("type", found[0]["ref"], value)
            return
        await asyncio.sleep(0.5)
    raise RuntimeError(f"找不到{label}输入框（选择器: {css}）——页面结构可能变了，请重跑 recon")


async def _ensure_agreement(tab: Tab, css: str) -> bool:
    """勾选服务使用协议复选框。

    Args: tab 页面标签; css 复选框选择器。Returns: 是否找到复选框。
    """
    try:
        state = await tab.evaluate(
            f"(function(){{var c=document.querySelector({json.dumps(css)});"
            f"if(!c) return 'missing'; if(c.checked) return 'checked'; c.click(); return 'clicked';}})()"
        )
    except Exception as exc:  # noqa: BLE001 页面上下文切换期间的评估失败按未找到处理
        state = "missing"
        get_logger(__name__).debug("协议勾选检查失败: %s", exc)
    return state != "missing"


async def _click_login_button(tab: Tab, sel: dict, timeout: float = 10.0) -> bool:
    """定位并点击登录提交按钮（等待按钮渲染出现）。

    Args: tab 页面标签; sel 选择器集; timeout 最长等待秒。Returns: 是否成功点击。
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        btns = await tab.agent("find", sel["submit_button"], 3)
        if not btns:
            btns = await tab.agent("findByText", sel["submit_text"], "button", 3)
        if btns:
            await tab.agent("click", btns[0]["ref"])
            await asyncio.sleep(2.0)
            return True
        await asyncio.sleep(0.5)
    return False


async def _notify_captcha_if_visible(tab: Tab, ctx: AppContext, css: str) -> None:
    """滑块验证码可见时发 CAPTCHA_REQUIRED 事件（需人工完成）。"""
    try:
        visible = await tab.evaluate(
            f"(function(){{var f=document.querySelector({json.dumps(css)});"
            f"if(!f) return false; var r=f.getBoundingClientRect(); return r.width>50&&r.height>50;}})()"
        )
    except Exception as exc:  # noqa: BLE001 评估失败视为不可见
        visible = False
        get_logger(__name__).debug("滑块检测失败: %s", exc)
    if visible:
        await ctx.events.emit(Event(EventType.CAPTCHA_REQUIRED))


async def _handle_sms_challenge(tab: Tab, ctx: AppContext, sel: dict) -> None:
    """短信验证码流程：等 TUI 补输后填入并再次提交。"""
    try:
        sms = await tab.agent("find", sel["sms_input"], 3)
        sms = [d for d in sms if d.get("tag") == "input"]
    except Exception as exc:  # noqa: BLE001 无短信输入框属正常路径
        sms = []
        get_logger(__name__).debug("短信输入框探测失败: %s", exc)
    if not sms:
        return
    await ctx.events.emit(Event(EventType.SMS_REQUIRED))
    code = await _wait_sms_code(ctx)
    await tab.agent("type", sms[0]["ref"], code)
    await asyncio.sleep(0.3)
    submit2 = await tab.agent("find", sel["submit_button"], 3)
    if submit2:
        await tab.agent("click", submit2[0]["ref"])


async def _password_login(ctx: AppContext, account: str, password: str) -> None:
    """账密登录主流程：导航 → 填表 → 勾协议 → 提交 → 人工辅助 → 轮询结果。

    Globals Used: None。Calls: _fill_input/_ensure_agreement/_click_login_button/
    _notify_captcha_if_visible/_handle_sms_challenge/_wait_login。
    Args: ctx 上下文; account 账号; password 密码（不进 LLM）。Returns: None。
    """
    sel = _selectors()
    tab = ctx.require_tab()
    await tab.navigate(sel["auth_url"])

    await _fill_input(tab, sel["account_input"], account, "账号")
    await _fill_input(tab, sel["password_input"], password, "密码")
    if not await _ensure_agreement(tab, sel["agreement_checkbox"]):
        await ctx.events.emit(Event(EventType.STATUS, text="未找到协议勾选框，若登录失败请手动勾选"))
    if not await _click_login_button(tab, sel):
        await ctx.events.emit(Event(EventType.LOGIN_RESULT, ok=False,
                                    message="找不到登录按钮，请在浏览器手动登录，我方会自动检测"))
        return
    await _notify_captcha_if_visible(tab, ctx, sel["captcha_iframe"])
    await _handle_sms_challenge(tab, ctx, sel)

    ok = await _wait_login(ctx, timeout=90)
    ctx.state["xiumi_logged_in"] = ok


async def _wait_sms_code(ctx: AppContext, timeout: float = 180) -> str:
    """等 TUI 把验证码写进 ctx.state['sms_code']。"""
    ev = asyncio.Event()
    ctx.state.setdefault("_sms_events", []).append(ev)
    try:
        await asyncio.wait_for(ev.wait(), timeout=timeout)
        return str(ctx.state.get("sms_code", ""))
    finally:
        ctx.state["_sms_events"].remove(ev)


def _notify_sms_code(ctx: AppContext, code: str) -> None:
    ctx.state["sms_code"] = code
    for ev in list(ctx.state.get("_sms_events", [])):
        ev.set()


async def _tool_login_check(ctx: AppContext, args: dict) -> str:
    ok = await check_login(ctx)
    return "已登录" if ok else "未登录，请提示用户输入 /login 命令完成登录"


class XiumiLoginPlugin(Plugin):
    name = "xiumi_login"
    description = "秀米登录：登录态检查工具 + 账密登录动作（终端内完成，凭据不进 LLM）"

    def actions(self, ctx: AppContext) -> dict:
        return {
            "xiumi_login.password": _password_login,
            "xiumi_login.check": lambda: check_login(ctx),
            "xiumi_login.sms_code": lambda code: _notify_sms_code(ctx, code),
        }

    def tools(self, ctx: AppContext) -> list[Tool]:
        return [
            Tool(
                name="xiumi_login_check",
                description="检查当前是否已登录秀米，返回 已登录/未登录",
                parameters={"type": "object", "properties": {}},
                handler=_tool_login_check,
            )
        ]
