"""xiumi_login 插件：登录态检查 + 两种登录动作（供 TUI 直接调用，凭据不经过 LLM）。

- 动作 xiumi_login.qr       扫码登录：点微信图标 → 新标签页截二维码 → 弹出图片 → 轮询登录态
- 动作 xiumi_login.password  账密登录：TUI 模态框收集账号密码 → 代填页面（含协议勾选）→ 提交；
                               若出现滑块验证码/短信验证码，通知用户在浏览器里人工辅助
- 工具 xiumi_login_check     供 LLM 查询登录态（只读）

选择器已实地踩点确认（见同目录 selectors.json）。
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from cdp.helpers import Tab
from core.registry import AppContext, Plugin, Tool

HERE = Path(__file__).parent


def _selectors() -> dict:
    return json.loads((HERE / "selectors.json").read_text(encoding="utf-8"))


async def check_login(ctx: AppContext, navigate: bool = True) -> bool:
    """登录态检查：优先 selectors.json 的 check_js，否则看页面是否还有「登录」入口。"""
    tab = ctx.require_tab()
    sel = _selectors()
    url = await tab.current_url()
    if navigate and "xiumi.us" not in url:
        await tab.navigate(sel["home_url"])
        url = await tab.current_url()
    if "xiumi.us" not in url:
        return False
    if sel.get("check_js"):
        logged_in = bool(await tab.evaluate(sel["check_js"]))
    else:
        # 启发式：未登录时页面显著位置有「登录」字样（首页/登录页标题都会出现）
        res = await tab.evaluate(
            "(function(){var t=(document.body.innerText||'').slice(0,3000);"
            "return /登\\s*录|立即登录/.test(t);})()"
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


async def _qr_login(ctx: AppContext) -> None:
    """扫码登录：点微信图标（可能新开标签页），截二维码弹图，轮询直到登录成功。"""
    sel = _selectors()
    tab = ctx.require_tab()
    await tab.navigate(sel["auth_url"])

    # 点击微信登录图标（wechat-chapter 下第一个 void(0) 图标链接，按 微信/QQ/微博 顺序）
    links = await tab.agent("find", sel["wechat_link_selector"], 10)
    links = [d for d in links if d.get("tag") == "a"]
    if not links:
        await ctx.events.emit("login_result", ok=False, message="找不到微信登录图标，请手动在浏览器里点击微信登录后，我方会自动检测")
    else:
        await tab.agent("click", links[sel.get("wechat_link_index", 0)]["ref"])
        await asyncio.sleep(2.5)

    # 二维码可能在：新标签页（微信 OAuth 窗口）或当前页弹出层
    qr_tab = await _find_qr_tab(ctx)
    target = qr_tab or tab
    qr_path = ctx.config.screenshots_dir / "login_qr.png"
    ok_shot = False
    if qr_tab is not None:
        for selector in [s.strip() for s in sel["qr_selector"].split(",") if s.strip()]:
            try:
                if await qr_tab.wait_selector(selector, timeout=4):
                    await qr_tab.screenshot(path=qr_path, selector=selector)
                    ok_shot = True
                    break
            except Exception:
                continue
    if not ok_shot:
        try:
            await target.screenshot(path=qr_path)  # 兜底整页截图，人眼找码
            ok_shot = True
        except Exception:
            pass
    if ok_shot:
        await ctx.events.emit("qr_ready", path=str(qr_path))
        try:
            os.startfile(str(qr_path))
        except Exception:
            pass
    else:
        await ctx.events.emit("login_result", ok=False, message="二维码截图失败，请在浏览器窗口里直接扫码")
        return

    ok = await _wait_login(ctx, timeout=240)
    ctx.state["xiumi_logged_in"] = ok
    if ok:
        await ctx.events.emit("login_result", ok=True, message="扫码登录成功")
    else:
        await ctx.events.emit("login_result", ok=False, message="等待扫码超时（4 分钟），可重试或改用账号密码")


async def _find_qr_tab(ctx: AppContext) -> Tab | None:
    """微信 OAuth 点击后若弹出了新标签页（open.weixin.qq.com 等），attach 并返回。"""
    if not ctx.cdp:
        return None
    try:
        pages = await ctx.cdp.list_pages()
    except Exception:
        return None
    for p in pages:
        url = p.get("url", "")
        if any(kw in url for kw in ("open.weixin.qq.com", "graph.qq.com", "api.weibo.com")):
            session_id = await ctx.cdp.attach(p["targetId"])
            qr_tab = Tab(ctx.cdp, session_id, p)
            await qr_tab.enable()
            return qr_tab
    return None


async def _fill_input(tab: Tab, css: str, value: str, label: str) -> None:
    found = await tab.agent("find", css, 5)
    if not found:
        raise RuntimeError(f"找不到{label}输入框（选择器: {css}）——页面结构可能变了，请重跑 recon")
    await tab.agent("click", found[0]["ref"])
    await tab.agent("type", found[0]["ref"], value)


async def _password_login(ctx: AppContext, account: str, password: str) -> None:
    """账密登录：填表 → 勾协议 → 提交；滑块/短信验证码需要用户人工辅助。"""
    sel = _selectors()
    tab = ctx.require_tab()
    await tab.navigate(sel["auth_url"])

    await _fill_input(tab, sel["account_input"], account, "账号")
    await _fill_input(tab, sel["password_input"], password, "密码")

    # 勾选《服务使用协议》（默认未勾选，不勾无法登录）
    try:
        checked = await tab.evaluate(
            f"(function(){{var c=document.querySelector({json.dumps(sel['agreement_checkbox'])});"
            f"if(!c) return 'missing'; if(c.checked) return 'checked'; c.click(); return 'clicked';}})()"
        )
    except Exception:
        checked = "missing"
    if checked == "missing":
        await ctx.events.emit("status", text="未找到协议勾选框，若登录失败请手动勾选")

    btns = await tab.agent("find", sel["submit_button"], 3)
    if not btns:
        btns = await tab.agent("findByText", sel["submit_text"], "button", 3)
    if not btns:
        await ctx.events.emit("login_result", ok=False, message="找不到登录按钮，请在浏览器手动登录，我方会自动检测")
        return
    await tab.agent("click", btns[0]["ref"])
    await asyncio.sleep(2.0)

    # 腾讯滑块验证码：自动化不可行，浏览器就在用户眼前，提示人工滑动
    captcha_visible = False
    try:
        captcha_visible = await tab.evaluate(
            f"(function(){{var f=document.querySelector({json.dumps(sel['captcha_iframe'])});"
            f"if(!f) return false; var r=f.getBoundingClientRect(); return r.width>50&&r.height>50;}})()"
        )
    except Exception:
        pass
    if captcha_visible:
        await ctx.events.emit("captcha_required")

    # 短信验证码
    try:
        sms = await tab.agent("find", sel["sms_input"], 3)
        sms = [d for d in sms if d.get("tag") == "input"]
    except Exception:
        sms = []
    if sms:
        await ctx.events.emit("sms_required")
        code = await _wait_sms_code(ctx)
        await tab.agent("type", sms[0]["ref"], code)
        await asyncio.sleep(0.3)
        submit2 = await tab.agent("find", sel["submit_button"], 3)
        if submit2:
            await tab.agent("click", submit2[0]["ref"])

    ok = await _wait_login(ctx, timeout=90)
    ctx.state["xiumi_logged_in"] = ok
    if ok:
        await ctx.events.emit("login_result", ok=True, message="账号密码登录成功")
    else:
        await ctx.events.emit(
            "login_result",
            ok=False,
            message="登录未成功（密码错误/滑块未完成/页面变化）。请在浏览器窗口手动完成验证，或改用扫码",
        )


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
    return "已登录" if ok else "未登录（需要用户在 TUI 界面完成登录，Agent 无法代劳扫码/输密码）"


class XiumiLoginPlugin(Plugin):
    name = "xiumi_login"
    description = "秀米登录：登录态检查工具 + 扫码/账密登录动作（动作由 TUI 调用，凭据不进 LLM）"

    def actions(self, ctx: AppContext) -> dict:
        return {
            "xiumi_login.qr": _qr_login,
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
