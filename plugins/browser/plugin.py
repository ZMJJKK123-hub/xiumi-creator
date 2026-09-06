"""browser 插件：通用网页操控工具（任何网站都能用，不含秀米业务逻辑）。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from plugins.tool_browser.backend import get_aux_tab

from core.registry import AppContext, Plugin, Tool


def _tab_for(ctx: AppContext, args: dict):
    """按 background 参数选择目标：False=主标签页(默认)，True=后台工具箱浏览器。"""
    if args.get("background"):
        return get_aux_tab(ctx)
    return ctx.require_tab()


async def _navigate(ctx: AppContext, args: dict) -> str:
    url = args["url"]
    if not url.startswith(("http://", "https://")):
        return "ERROR: url 必须以 http:// 或 https:// 开头"
    tab = ctx.require_tab()
    await tab.navigate(url)
    title = await tab.evaluate("document.title")
    return f"已导航到 {url}（标题: {title}）"


async def _outline(ctx: AppContext, args: dict) -> str:
    tab = ctx.require_tab()
    tree = await tab.agent("outline")
    return json.dumps(tree, ensure_ascii=False)


async def _click(ctx: AppContext, args: dict) -> str:
    tab = ctx.require_tab()
    await tab.agent("click", int(args["ref"]))
    await _sleep(0.6)
    return f"已点击 ref={args['ref']}"


async def _type(ctx: AppContext, args: dict) -> str:
    tab = ctx.require_tab()
    await tab.agent("type", int(args["ref"]), str(args["text"]))
    await _sleep(0.3)
    return f"已向 ref={args['ref']} 输入文本（{len(str(args['text']))} 字符）"


async def _press_key(ctx: AppContext, args: dict) -> str:
    tab = ctx.require_tab()
    key = args["key"]
    try:
        await tab.agent("press", key)
        accepted = True
    except Exception:
        accepted = False
    if not accepted or args.get("real"):
        await tab.real_press(key)  # CDP 真实按键兜底
    return f"已按键 {key}"


async def _exec_js(ctx: AppContext, args: dict) -> str:
    tab = _tab_for(ctx, args)
    code = args["code"]
    await_promise = bool(args.get("await_promise", False))
    value = await tab.evaluate(code, await_promise=await_promise)
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


async def _screenshot(ctx: AppContext, args: dict) -> str:
    tab = _tab_for(ctx, args)
    name = args.get("filename") or time.strftime("shot_%H%M%S.png")
    path = Path(name)
    if not path.is_absolute():
        path = ctx.config.screenshots_dir / path
    if path.suffix.lower() != ".png":
        path = path.with_suffix(".png")
    out = await tab.screenshot(path=path, selector=args.get("selector"))
    await ctx.events.emit("screenshot", path=str(out))
    return f"截图已保存: {out}"


async def _get_text(ctx: AppContext, args: dict) -> str:
    tab = ctx.require_tab()
    text = await tab.agent("getText", int(args["ref"]), int(args.get("max", 3000)))
    return text or "(空)"


async def _sleep(sec: float) -> None:
    import asyncio

    await asyncio.sleep(sec)


class BrowserPlugin(Plugin):
    name = "browser"
    description = "通用网页操控：导航、元素树观察、点击、输入、执行 JS、截图"

    def tools(self, ctx: AppContext) -> list[Tool]:
        return [
            Tool(
                name="browser_navigate",
                description="让当前标签页导航到指定 URL（http/https）",
                parameters={
                    "type": "object",
                    "properties": {"url": {"type": "string", "description": "完整 URL"}},
                    "required": ["url"],
                },
                handler=_navigate,
            ),
            Tool(
                name="browser_dom_outline",
                description=(
                    "获取当前页面的精简元素树（可交互元素/含文本元素/iframe），"
                    "每个元素带 ref 引用，供 click/type/getText 使用。ref 在下次 outline/find 后失效。"
                ),
                parameters={"type": "object", "properties": {}},
                handler=_outline,
            ),
            Tool(
                name="browser_click",
                description="点击 dom_outline 中 ref 对应的元素",
                parameters={
                    "type": "object",
                    "properties": {"ref": {"type": "integer", "description": "outline 中的元素引用号"}},
                    "required": ["ref"],
                },
                handler=_click,
            ),
            Tool(
                name="browser_type",
                description="向 ref 对应的输入框/编辑区输入文本（整体替换内容）",
                parameters={
                    "type": "object",
                    "properties": {
                        "ref": {"type": "integer"},
                        "text": {"type": "string"},
                    },
                    "required": ["ref", "text"],
                },
                handler=_type,
            ),
            Tool(
                name="browser_press_key",
                description="对当前焦点元素按键（Enter/Tab/Escape/Backspace/方向键等）。合成事件无效时自动走 CDP 真实按键。",
                parameters={
                    "type": "object",
                    "properties": {"key": {"type": "string", "description": "键名，如 Enter"}},
                    "required": ["key"],
                },
                handler=_press_key,
            ),
            Tool(
                name="browser_exec_js",
                description=(
                    "在页面里执行任意 JS 并返回结果（万能兜底）。页面已内置 window.__agent 工具函数："
                    "find(css选择器)->[{ref,...}]、findByText(文本)->[{ref,...}]、click(ref)、type(ref,text)、"
                    "getText(ref)、pasteHTML(html,selector?)、focusEnd(selector)、appendHTML(html,selector)、triggerChange(selector)。"
                    "默认作用于主标签页；background=true 时作用于 browser_open 打开的后台浏览器。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "JS 表达式或语句（有返回值）"},
                        "await_promise": {"type": "boolean", "description": "是否等待 Promise，默认 false"},
                        "background": {"type": "boolean", "description": "true=后台工具箱浏览器，默认 false 主标签页"},
                    },
                    "required": ["code"],
                },
                handler=_exec_js,
            ),
            Tool(
                name="browser_capture",
                description="页面截图（全页或指定元素），保存到 screenshots/ 目录，返回文件路径。默认主标签页；background=true 时截 browser_open 打开的后台浏览器",
                parameters={
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "文件名（可省略自动命名）"},
                        "selector": {"type": "string", "description": "CSS 选择器，只截该元素（可省略截可视区）"},
                        "background": {"type": "boolean", "description": "true=后台工具箱浏览器，默认 false 主标签页"},
                    },
                },
                handler=_screenshot,
            ),
            Tool(
                name="browser_get_text",
                description="读取 ref 对应元素的文本内容",
                parameters={
                    "type": "object",
                    "properties": {
                        "ref": {"type": "integer"},
                        "max": {"type": "integer", "description": "最多返回字符数，默认 3000"},
                    },
                    "required": ["ref"],
                },
                handler=_get_text,
            ),
        ]
