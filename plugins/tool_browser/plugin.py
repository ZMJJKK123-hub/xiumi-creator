"""tool_browser 插件：后台浏览器工具箱（自 dsh-plugins/packages/tool-browser 适配）。

只保留它独有能力对应的生命周期工具：
  browser_open(url, headless) / browser_close()
对后台浏览器的 JS 执行与截图复用主插件更强的 browser_exec_js / browser_capture
（background=true 参数），避免同型工具重复装载。
"""
from __future__ import annotations

from core.registry import AppContext, Plugin, Tool

from plugins.tool_browser.backend import close_aux, open_aux


async def _t_open(ctx: AppContext, args: dict) -> str:
    url = args["url"]
    if not url.startswith(("http://", "https://", "file://", "about:")):
        return "ERROR: url 需以 http:// 或 https:// 开头"
    res = await open_aux(ctx, url, bool(args.get("headless", True)))
    return (
        f"已打开后台浏览器（handle: {res['handle']}，无头: {res['headless']}）→ {res['url']}。"
        "操作/截图请用 browser_exec_js / browser_capture 并传 background=true"
    )


async def _t_close(ctx: AppContext, args: dict) -> str:
    closed = await close_aux(ctx)
    return "后台浏览器已关闭" if closed else "没有需要关闭的后台浏览器"


class ToolBrowserPlugin(Plugin):
    name = "tool_browser"
    description = "后台浏览器工具箱（dsh 适配）：独立 Edge 实例的打开与关闭；执行/截图用主插件工具的 background 参数"

    def tools(self, ctx: AppContext) -> list[Tool]:
        return [
            Tool(
                name="browser_open",
                description=(
                    "在后台（独立 Edge 实例，默认无头、临时 profile）打开一个网页。"
                    "用于临时查资料、打开测试页面等，不影响正在操作的秀米标签页。"
                    "之后用 browser_exec_js / browser_capture 并传 background=true 操作它。重复调用会替换已有实例。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "要打开的网址，例如 https://example.com"},
                        "headless": {"type": "boolean", "description": "是否无头运行（默认 true，不显示窗口）"},
                    },
                    "required": ["url"],
                },
                handler=_t_open,
            ),
            Tool(
                name="browser_close",
                description="关闭后台工具箱浏览器，释放资源（不影响秀米主标签页）",
                parameters={"type": "object", "properties": {}},
                handler=_t_close,
            ),
        ]

    async def on_unload(self, ctx: AppContext) -> None:
        await close_aux(ctx)
