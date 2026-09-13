"""工具注册表 + 插件契约 + 插件管理器。

插件 = plugins/<name>/plugin.py 中的一个 Plugin 子类。
  - tools():   暴露给 LLM 的工具（function calling）
  - actions(): 只给 TUI/内部调用的动作（如登录，凭据不进 LLM 上下文）
  - on_load(): 插件加载钩子
"""
from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from core.config import Config
from core.events import EventBus

from cdp.connection import CDPConnection
from cdp.helpers import Tab


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: Callable[[Any, dict], Awaitable[str]]  # async (ctx, args) -> 工具结果文本


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具名冲突: {tool.name} 已被注册")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    async def call(self, ctx: "AppContext", name: str, args: dict) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"ERROR: 未知工具 {name}（可用: {', '.join(self.names())}）"
        result = await tool.handler(ctx, args or {})
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        limit = ctx.config.tool_result_max_chars
        if len(text) > limit:
            text = text[:limit] + f"\n...[结果过长已截断，共 {len(text)} 字符]"
        return text


class AppContext:
    """贯穿全局的上下文：工具/插件/TUI 都通过它访问浏览器与状态。"""

    def __init__(self, config: Config, events: EventBus):
        self.config = config
        self.events = events
        self.cdp: CDPConnection | None = None
        self.tab: Tab | None = None
        self.state: dict[str, Any] = {}  # 插件共享状态（如 draft 信息、登录态）

    def require_tab(self) -> Tab:
        if not self.tab:
            raise RuntimeError("浏览器标签页尚未就绪")
        return self.tab


class Plugin:
    name: str = ""
    description: str = ""

    def tools(self, ctx: AppContext) -> list[Tool]:
        return []

    def actions(self, ctx: AppContext) -> dict[str, Callable]:
        """返回 {'插件名.动作名': async callable}，仅供 TUI/内部直接调用。"""
        return {}

    async def on_load(self, ctx: AppContext) -> None:
        pass

    async def on_unload(self, ctx: AppContext) -> None:
        pass


class PluginManager:
    def __init__(self, plugins_root: Path, registry: ToolRegistry):
        self.root = plugins_root
        self.registry = registry
        self.plugins: dict[str, Plugin] = {}
        self.actions: dict[str, Callable] = {}

    def discover_and_load(self, ctx: AppContext) -> None:
        for plugin_py in sorted(self.root.glob("*/plugin.py")):
            mod_name = f"plugin_{plugin_py.parent.name}"
            spec = importlib.util.spec_from_file_location(mod_name, plugin_py)
            if not spec or not spec.loader:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cls = next(
                (obj for obj in vars(mod).values() if isinstance(obj, type) and issubclass(obj, Plugin) and obj is not Plugin),
                None,
            )
            if cls is None:
                continue
            plugin = cls()
            self.plugins[plugin.name or plugin_py.parent.name] = plugin

    async def load_all(self, ctx: AppContext) -> None:
        self.discover_and_load(ctx)
        for name, plugin in self.plugins.items():
            await plugin.on_load(ctx)
            for tool in plugin.tools(ctx):
                self.registry.register(tool)
            self.actions.update(plugin.actions(ctx))
