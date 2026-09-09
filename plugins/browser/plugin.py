"""browser 插件：主标签页通用操控（导航/观察/交互/执行/截图）。

Rule1 §6.2：一工具一工厂，新增工具加函数即可（OCP）；
全部操作经 _tab_for 支持主标签页与后台工具箱双目标。
"""
from __future__ import annotations

import asyncio  # 交互后短暂等待页面反应
import json  # exec_js 结果序列化
import time  # 截图默认文件名时间戳
from pathlib import Path  # 截图路径拼接
from typing import Any  # 类型标注

from core.registry import AppContext, Plugin, Tool  # 插件契约
from plugins.tool_browser.backend import get_aux_tab  # background=true 时取后台浏览器标签页


def _tab_for(ctx: AppContext, args: dict) -> Any:
    """按 background 参数选择目标标签页。

    Args: ctx 全局上下文; args 工具参数。Returns: Tab 实例。
    """
    if args.get("background"):
        return get_aux_tab(ctx)
    return ctx.require_tab()


async def _navigate(ctx: AppContext, args: dict) -> str:
    """browser_navigate 处理器：主标签页导航。

    Args: ctx; args 含 url。Returns: 结果文本。
    """
    url = args["url"]
    if not url.startswith(("http://", "https://")):
        return "ERROR: url 必须以 http:// 或 https:// 开头"
    tab = ctx.require_tab()
    await tab.navigate(url)
    title = await tab.evaluate("document.title")
    return f"已导航到 {url}，标题: {title}"


async def _outline(ctx: AppContext, args: dict) -> str:
    """browser_dom_outline 处理器：精简元素树（ref 引用）。

    Args: ctx; args 空。Returns: JSON 文本。
    """
    return json.dumps(await ctx.require_tab().agent("outline"), ensure_ascii=False)


async def _click(ctx: AppContext, args: dict) -> str:
    """browser_click 处理器：点击 ref 元素。

    Args: ctx; args 含 ref。Returns: 结果文本。
    """
    await ctx.require_tab().agent("click", int(args["ref"]))
    await asyncio.sleep(0.6)
    return f"已点击 ref={args['ref']}"


async def _type(ctx: AppContext, args: dict) -> str:
    """browser_type 处理器：向 ref 元素输入文本。

    Args: ctx; args 含 ref/text。Returns: 结果文本。
    """
    await ctx.require_tab().agent("type", int(args["ref"]), str(args["text"]))
    await asyncio.sleep(0.3)
    return f"已向 ref={args['ref']} 输入文本"


async def _press_key(ctx: AppContext, args: dict) -> str:
    """browser_press_key 处理器：合成按键，失效时走 CDP 真实按键。

    Args: ctx; args 含 key。Returns: 结果文本。
    """
    tab = ctx.require_tab()
    key = args["key"]
    try:
        await tab.agent("press", key)
    except Exception:  # noqa: BLE001 合成事件不生效属预期路径，转真实按键
        await tab.real_press(key)
    return f"已按键 {key}"


async def _exec_js(ctx: AppContext, args: dict) -> str:
    """browser_exec_js 处理器：执行任意 JS（万能兜底）。

    Args: ctx; args 含 code/await_promise/background。Returns: 序列化结果。
    """
    tab = _tab_for(ctx, args)
    value = await tab.evaluate(args["code"], await_promise=bool(args.get("await_promise", False)))
    if value is None:
        return "null"
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


async def _screenshot(ctx: AppContext, args: dict) -> str:
    """browser_capture 处理器：页面/元素截图到 screenshots 目录。

    Args: ctx; args 含 filename/selector/background。Returns: 保存路径。
    """
    from core.events import Event, EventType  # 局部导入：截图完成事件

    tab = _tab_for(ctx, args)
    name = args.get("filename") or time.strftime("shot_%H%M%S.png")
    path = Path(name)
    if not path.is_absolute():
        path = ctx.config.screenshots_dir / path
    out = await tab.screenshot(path=path.with_suffix(".png"), selector=args.get("selector"))
    await ctx.events.emit(Event(EventType.SCREENSHOT, path=str(out)))
    return f"截图已保存: {out}"


async def _get_text(ctx: AppContext, args: dict) -> str:
    """browser_get_text 处理器：读 ref 元素文本。

    Args: ctx; args 含 ref/max。Returns: 元素文本。
    """
    text = await ctx.require_tab().agent("getText", int(args["ref"]), int(args.get("max", 3000)))
    return text or "(空)"


def _t_navigate() -> Tool:
    """构造 browser_navigate 工具声明。Args: None。Returns: Tool。"""
    return Tool("browser_navigate", "让当前标签页导航到指定 URL",
                {"type": "object", "properties": {"url": {"type": "string", "description": "完整 URL"}},
                 "required": ["url"]}, _navigate)


def _t_outline() -> Tool:
    """构造 browser_dom_outline 工具声明。Args: None。Returns: Tool。"""
    return Tool("browser_dom_outline",
                "获取页面精简元素树，元素带 ref 供 click/type/getText 使用，ref 在下次 outline 后失效",
                {"type": "object", "properties": {}}, _outline)


def _t_click() -> Tool:
    """构造 browser_click 工具声明。Args: None。Returns: Tool。"""
    return Tool("browser_click", "点击 dom_outline 中 ref 对应的元素",
                {"type": "object", "properties": {"ref": {"type": "integer", "description": "元素引用号"}},
                 "required": ["ref"]}, _click)


def _t_type() -> Tool:
    """构造 browser_type 工具声明。Args: None。Returns: Tool。"""
    return Tool("browser_type", "向 ref 对应的输入框/编辑区输入文本",
                {"type": "object", "properties": {"ref": {"type": "integer"}, "text": {"type": "string"}},
                 "required": ["ref", "text"]}, _type)


def _t_press() -> Tool:
    """构造 browser_press_key 工具声明。Args: None。Returns: Tool。"""
    return Tool("browser_press_key", "对当前焦点元素按键，合成事件无效时自动走真实按键",
                {"type": "object", "properties": {"key": {"type": "string", "description": "键名如 Enter"}},
                 "required": ["key"]}, _press_key)


def _t_exec() -> Tool:
    """构造 browser_exec_js 工具声明（含 __agent 库说明）。Args: None。Returns: Tool。"""
    return Tool("browser_exec_js",
                "在页面执行任意 JS 并返回结果。页面已内置 window.__agent：find(css)/findByText(文本)/"
                "click(ref)/type(ref,text)/getText(ref)/pasteHTML(html,selector?)/focusEnd(selector)/"
                "appendHTML(html,selector)/triggerChange(selector)。默认主标签页，background=true 时作用于"
                "browser_open 打开的后台浏览器",
                {"type": "object",
                 "properties": {"code": {"type": "string", "description": "JS 表达式或语句"},
                                "await_promise": {"type": "boolean", "description": "是否等待 Promise"},
                                "background": {"type": "boolean", "description": "true=后台工具箱浏览器"}},
                 "required": ["code"]}, _exec_js)


def _t_capture() -> Tool:
    """构造 browser_capture 工具声明。Args: None。Returns: Tool。"""
    return Tool("browser_capture", "页面截图，支持 selector 元素裁剪，保存到 screenshots/ 目录",
                {"type": "object",
                 "properties": {"filename": {"type": "string", "description": "文件名，可省略自动命名"},
                                "selector": {"type": "string", "description": "CSS 选择器，只截该元素"},
                                "background": {"type": "boolean", "description": "true=后台工具箱浏览器"}},
                 }, _screenshot)


def _t_get_text() -> Tool:
    """构造 browser_get_text 工具声明。Args: None。Returns: Tool。"""
    return Tool("browser_get_text", "读取 ref 对应元素的文本内容",
                {"type": "object",
                 "properties": {"ref": {"type": "integer"}, "max": {"type": "integer", "description": "最多返回字符数"}},
                 "required": ["ref"]}, _get_text)


class BrowserPlugin(Plugin):
    """browser 插件：主标签页通用网页操控。

    类职责：注册导航/观察/交互/执行/截图等通用工具。
    类变量：name/description 插件元信息。
    生命周期：PluginManager 装载时实例化并调用 tools() 注册。
    """

    name = "browser"
    description = "通用网页操控：导航、元素树观察、点击、输入、执行 JS、截图"

    def tools(self, ctx: AppContext) -> list[Tool]:
        """汇总全部工具声明。

        Args: ctx 上下文（本插件不使用）。Returns: Tool 列表。
        """
        return [_t_navigate(), _t_outline(), _t_click(), _t_type(), _t_press(), _t_exec(), _t_capture(), _t_get_text()]
