"""tool_browser 插件：后台辅助浏览器（独立 Edge 实例，默认无头）。

架构定位：plugins 插件层；与 browser 插件的分工——browser 管主标签页
（秀米主战场），本插件开独立临时实例查资料/试页面，互不干扰；
对它的 JS 执行/截图复用 browser 插件的 background=true 参数，避免同型工具重复。


只保留它独有能力对应的生命周期工具：
  browser_open(url, headless) / browser_close()
对后台浏览器的 JS 执行与截图复用主插件更强的 browser_exec_js / browser_capture
（background=true 参数），避免同型工具重复装载。
"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

from core.registry import AppContext, Plugin, Tool  # 插件契约与工具 DTO

from plugins.tool_browser.backend import close_aux, open_aux  # 后台浏览器实例生命周期


async def _t_open(ctx: AppContext, args: dict) -> str:
    """browser_open 处理器：校验 url 后打开后台浏览器。 Args: ctx 上下文; args 含 url/headless。Returns: 结果文本（带后续操作指引）。"""
    url = args["url"]
    if not url.startswith(("http://", "https://", "file://", "about:")):
        return "ERROR: url 需以 http:// 或 https:// 开头"
    res = await open_aux(ctx, url, bool(args.get("headless", True)))
    return (
        f"已打开后台浏览器（handle: {res['handle']}，无头: {res['headless']}）→ {res['url']}。"
        "操作/截图请用 browser_exec_js / browser_capture 并传 background=true"
    )


async def _t_close(ctx: AppContext, args: dict) -> str:
    """browser_close 处理器：关闭后台浏览器。Args: ctx; args 占位。Returns: 结果文本。"""
    closed = await close_aux(ctx)
    return "后台浏览器已关闭" if closed else "没有需要关闭的后台浏览器"


class ToolBrowserPlugin(Plugin):
    """后台浏览器插件：独立 Edge 实例的打开/关闭（查资料、测试页）。

    类职责：只提供后台实例生命周期工具；执行/截图复用主插件 background 参数。
    属性：name/description 插件元信息。
    生命周期：PluginManager 装载 → on_unload 时关闭后台实例。
    """

    name = "tool_browser"
    description = "后台浏览器工具箱（dsh 适配）：独立 Edge 实例的打开与关闭；执行/截图用主插件工具的 background 参数"

    def tools(self, ctx: AppContext) -> list[Tool]:
        """注册后台浏览器工具。Calls: Tool 构造。Args: ctx。Returns: 工具列表。"""
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
        """卸载钩子：关闭后台实例。Calls: close_aux。Args: ctx。Returns: None。"""
        await close_aux(ctx)
