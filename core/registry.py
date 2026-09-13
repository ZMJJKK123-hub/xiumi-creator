"""插件系统：核心与能力的扩展边界（本项目"插件化"的心脏）。

架构定位：core 业务层；三重角色——①Tool/Plugin 契约（核心不知道任何
具体插件，新能力=新目录）；②ToolRegistry 工具表（LLM function calling
的声明与分发）；③AppContext 依赖容器（config/events/cdp/tab/state，
贯穿全层共享，boot 组装期填充）。装载链：PluginManager 扫描
plugins/*/plugin.py → on_load → tools()/actions() 注册进表。

  - tools():   暴露给 LLM 的工具（function calling）
  - actions(): 只给 TUI/内部调用的动作（如登录，凭据不进 LLM 上下文）
  - on_load(): 插件加载钩子
"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

import importlib.util  # 按文件路径动态装载插件模块
import json  # 工具结果序列化与截断
from dataclasses import dataclass  # Tool DTO
from pathlib import Path  # 插件根目录类型
from typing import Any, Awaitable, Callable  # 通用类型与处理器签名

from core.config import Config  # 全局配置（AppContext 持有）
from core.events import EventBus  # 事件总线（AppContext 持有）

from cdp.connection import CDPConnection  # 浏览器级连接（AppContext 持有）
from cdp.helpers import Tab  # 标签页封装（AppContext 持有）


@dataclass
class Tool:
    """工具 DTO：LLM function-calling 声明与处理器的绑定体。

    类职责：把 OpenAI 工具 schema 与本地 async 处理器一一对应。
    属性：name 工具名；description 给 LLM 的描述；parameters JSON Schema；
        handler async(ctx, args) -> 结果文本。
    生命周期：插件 tools() 构造 → 注册表登记 → Agent 循环调用。
    """

    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: Callable[[Any, dict], Awaitable[str]]  # async (ctx, args) -> 工具结果文本


class ToolRegistry:
    """工具注册表：登记、查询、schema 导出与统一调用入口。

    类职责：集中管理全部工具；名冲突即报错（禁止静默覆盖）。
    属性：_tools 工具名→Tool 映射。
    生命周期：App 构造创建 → 插件装载期 register → Agent 循环 schemas/call。
    """

    def __init__(self) -> None:
        """Args: None。"""
        self._tools: dict[str, Tool] = {}  # 工具名→Tool

    def register(self, tool: Tool) -> None:
        """登记工具。 Globals Used: None。Calls: 无。 Args: tool 工具 DTO。Returns: None；重名 raise ValueError。"""
        if tool.name in self._tools:
            raise ValueError(f"工具名冲突: {tool.name} 已被注册")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """按名取工具。Globals Used: None。Calls: 无。Args: name 工具名。Returns: Tool；不存在 raise KeyError。"""
        return self._tools[name]

    def names(self) -> list[str]:
        """全部工具名。Globals Used: None。Calls: 无。Args: None。Returns: 排序后的名字列表。"""
        return sorted(self._tools)

    def schemas(self) -> list[dict]:
        """导出 OpenAI function-calling 声明。Globals Used: None。Calls: 无。Args: None。Returns: schema dict 列表。"""
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
        """统一调用入口：执行工具并把结果规整为文本（超长截断）。

        Globals Used: None。Calls: tool.handler / json.dumps。
        Args: ctx 全局上下文; name 工具名; args 实参。Returns: 结果文本。
        """
        tool = self._tools.get(name)
        if not tool:
            return f"ERROR: 未知工具 {name}（可用: {', '.join(self.names())}）"
        result = await tool.handler(ctx, args or {})
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        limit = ctx.config.tool_result_max_chars
        if len(text) > limit:
            text = text[:limit] + f"...[结果过长已截断，共 {len(text)} 字符]"
        return text


class AppContext:
    """贯穿全局的依赖容器（三重角色见模块头）。

    类职责：持有配置、事件总线、CDP 连接、当前标签页与共享状态。
    属性：config 配置；events 事件总线；cdp 浏览器级连接；tab 当前标签页；
        state 插件共享状态（登录态、草稿信息等）。
    生命周期：App 构造创建 → boot 填充 cdp/tab → 全程注入各层。
    """

    def __init__(self, config: Config, events: EventBus):
        """Args: config 全局配置; events 事件总线。"""
        self.config = config  # 全局配置
        self.events = events  # 事件总线
        self.cdp: CDPConnection | None = None  # 浏览器级连接（boot 填充）
        self.tab: Tab | None = None  # 当前业务标签页（boot 填充）
        self.state: dict[str, Any] = {}  # 插件共享状态（如 draft 信息、登录态）

    def require_tab(self) -> Tab:
        """取当前标签页，未就绪即抛错。 Globals Used: None。Calls: 无。 Args: None。Returns: Tab；未就绪 raise RuntimeError。"""
        if not self.tab:
            raise RuntimeError("浏览器标签页尚未就绪")
        return self.tab


class Plugin:
    """插件契约基类：子类声明 tools/actions 与生命周期钩子。

    类职责：定义插件扩展点；核心不感知任何具体插件。
    属性：name 插件名；description 描述（子类覆盖）。
    生命周期：PluginManager 装载实例化 → on_load → tools/actions 被收集。
    """

    name: str = ""  # 插件唯一名（子类覆盖）
    description: str = ""  # 插件描述（子类覆盖）

    def tools(self, ctx: AppContext) -> list[Tool]:
        """暴露给 LLM 的工具。Calls: 子类实现。Args: ctx 上下文。Returns: Tool 列表（默认空）。"""
        return []

    def actions(self, ctx: AppContext) -> dict[str, Callable]:
        """内部动作表（凭据等敏感能力不进 LLM 上下文）。 Calls: 子类实现。Args: ctx 上下文。Returns: {'插件名.动作名': async callable}。"""
        return {}

    async def on_load(self, ctx: AppContext) -> None:
        """装载钩子。Calls: 子类实现。Args: ctx 上下文。Returns: None。"""
        pass

    async def on_unload(self, ctx: AppContext) -> None:
        """卸载钩子。Calls: 子类实现。Args: ctx 上下文。Returns: None。"""
        pass


class PluginManager:
    """插件管理器：发现、装载、注册工具与动作。

    类职责：扫描插件目录动态装载 Plugin 子类，聚合工具与动作。
    属性：root 插件根目录；registry 工具注册表；plugins 已装载插件表；
        actions 聚合动作表。
    生命周期：App 构造创建 → boot 调 load_all → 全程只读。
    """

    def __init__(self, plugins_root: Path, registry: ToolRegistry):
        """Args: plugins_root 插件根目录; registry 工具注册表。"""
        self.root = plugins_root  # 插件根目录
        self.registry = registry  # 工具注册表
        self.plugins: dict[str, Plugin] = {}  # 已装载插件
        self.actions: dict[str, Callable] = {}  # 聚合动作表

    def discover_and_load(self, ctx: AppContext) -> None:
        """扫描 */plugin.py 并实例化其中的 Plugin 子类。

        Globals Used: None。Calls: importlib 按路径装载。
        Args: ctx 上下文。Returns: None（无子类的目录跳过）。
        """
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
        """全量装载：钩子 + 工具注册 + 动作聚合。

        Globals Used: None。Calls: discover_and_load / plugin.on_load / registry.register。
        Args: ctx 上下文。Returns: None。
        """
        self.discover_and_load(ctx)
        for name, plugin in self.plugins.items():
            await plugin.on_load(ctx)
            for tool in plugin.tools(ctx):
                self.registry.register(tool)
            self.actions.update(plugin.actions(ctx))
