"""主应用薄壳：布局组装与事件接线（boot/commands/theme/spinner 各自独立成模块）。"""
from __future__ import annotations

import asyncio  # _set_window 的异步任务派发
import time  # 任务计时与截图命名
from pathlib import Path  # 路径类型与插件目录定位

import plugins as _plugins_pkg  # 已安装的插件包：定位插件目录（源码/安装两态一致）
from rich.text import Text  # 状态栏富文本
from textual.app import App, ComposeResult  # 应用基类与布局协议
from textual.containers import Horizontal  # 输入框/状态栏横向容器
from textual.widgets import Input, Rule, Static  # 基础组件

from cdp.browser import EdgeBrowser  # 自动化浏览器生命周期
from core.config import Config, XIUMI_HOME, load_config  # 配置解析与数据目录
from core.events import Event, EventBus, EventType  # 强类型事件总线
from core.llm import LLMClient  # OpenAI 兼容客户端（apply_model 重建用）
from core.log import get_logger  # 统一日志
from core.registry import AppContext, PluginManager, ToolRegistry  # 插件体系
from tui.actions import LLMConfigActions, ShortcutActions  # 快捷键与 LLM 配置 Mixin
from tui.boot import boot, make_login_result_minimizer  # 启动编排
from tui.commands import CommandRouter  # 斜杠命令路由
from tui.screens import HelpScreen  # 帮助浮层（PasswordScreen 由命令层打开）
from tui.spinner import SpinnerState  # spinner 状态机
from tui.theme import ACCENT, APP_CSS, GRAY, RED  # 主题常量与全局 CSS
from tui.widgets import Transcript  # 流水（输入框用通用 Input）
from tui.window import WindowScheduler  # 浏览器窗口显隐

# 插件目录：从已安装包定位
PLUGINS_DIR = Path(_plugins_pkg.__file__).resolve().parent


class XiumiAgentApp(LLMConfigActions, ShortcutActions, App):
    """xiumi-agent 主应用。

    类职责：组装布局与模态屏、把事件总线映射到流水、调度任务与快捷键。
    类变量：CSS（theme.APP_CSS）、BINDINGS（键位表）。
    实例：bus 总线、registry/plugins 工具体系、browser/ctx 浏览器上下文、
    agent 任务循环、commands 命令路由、spinner 状态机、log 日志。
    生命周期：on_mount 聚焦输入框并启动 boot worker → 交互 → ctrl+q 退出。
    """

    CSS = APP_CSS
    TITLE = "xiumi-agent"

    BINDINGS = [
        ("ctrl+q", "quit", "退出"),
        ("ctrl+l", "clear_logs", "清屏"),
        ("escape", "interrupt", "中断任务"),
        ("pageup", "scroll_transcript_up", "上翻消息"),
        ("pagedown", "scroll_transcript_down", "下翻消息"),
    ]

    def __init__(self) -> None:
        """初始化协作对象；浏览器/插件/agent 在 boot 阶段填充。"""
        super().__init__()
        self.config: Config = load_config()
        self.bus = EventBus()
        self.ctx = AppContext(self.config, self.bus)
        self.registry = ToolRegistry()
        self.plugins = PluginManager(PLUGINS_DIR, self.registry)
        self.browser: EdgeBrowser | None = None
        self.agent = None
        self.actions: dict = {}
        self.commands = CommandRouter()
        self.spinner = SpinnerState()
        self._window = WindowScheduler(self)
        self.logger = get_logger("app")
        self._busy = False
        self._boot_failed = False
        self._worker = None
        self._task_started = 0.0

    # ---- 布局 ----
    def compose(self) -> ComposeResult:
        """三区布局：流水 / spinner / 输入框 / 状态栏。"""
        yield Transcript(id="transcript")
        yield Static("", id="spinner")
        yield Rule(id="rule-top")
        with Horizontal(id="input-box"):
            yield Static("> ", id="prompt-sym")
            yield Input(placeholder='Try "写一篇秋天咖啡店探店推文"', id="task")
        yield Rule(id="rule-bot")
        yield Horizontal(
            Static("? 快捷键 · ↑↓ 历史", id="hint"),
            Static("", id="info"),
            id="footer",
        )

    def on_mount(self) -> None:
        """挂载：聚焦输入框、接线事件、启动 boot。"""
        self._wire_events()
        self.query_one("#task", Input).focus()
        self.set_interval(0.12, self._tick_spinner)
        self.run_worker(self._boot_task(), thread=False)

    async def _boot_task(self) -> None:
        """boot worker：调用 tui.boot 编排，取消仅记日志。"""
        try:
            await boot(self)
            make_login_result_minimizer(self)
        except asyncio.CancelledError:
            self.logger.info("boot 被取消")

    # ---- 事件总线 → 流水 ----
    def _wire_events(self) -> None:
        """订阅系统事件并映射到流水/状态栏/浏览器窗口。"""
        bus, t = self.bus, self.transcript()
        bus.on(EventType.CHAT, lambda e: self._chat(e.role, e.text))
        bus.on(EventType.ACTION, lambda e: t.write_action(e.name, e.args))
        bus.on(EventType.TOOL_RESULT, lambda e: t.write_result(e.name, e.result))
        bus.on(EventType.STATUS, lambda e: self.set_status(e.text, e.error))
        bus.on(EventType.SCREENSHOT, lambda e: t.write_tool_note(f"截图: {e.path}"))
        bus.on(EventType.ERROR, lambda e: t.write_system("⚠ " + e.message))
        bus.on(EventType.CAPTCHA_REQUIRED, lambda e: self._set_window("normal"))
        bus.on(EventType.TASK_DONE, self._on_task_done)

    def _on_task_done(self, event: Event) -> None:
        """任务结束：解除忙碌并写统计行。"""
        self._set_busy(False)
        mark = "✻" if event.ok else "⚠"
        self.transcript().write_system(f"{mark} {event.message}")

    # ---- 用户输入 ----
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """提交处理：模态屏激活时不处理（防模态输入冒泡成任务/凭据泄露）；
        主屏则回显命令条 → 命令路由 → 未消费则作为任务执行。"""
        if len(self.screen_stack) > 1:
            event.stop()
            return
        raw = event.value.strip()
        if not raw:
            event.input.value = ""
            return
        event.input.value = ""
        self.transcript().write_user(raw)
        if await self.commands.dispatch(self, raw):
            return
        if self._can_run_task():
            self._start_task(raw)

    def _can_run_task(self) -> bool:
        """任务前置校验：忙碌/LLM/浏览器三关卡。"""
        if self._busy:
            self._chat("system", "⏳ 上一轮任务还在进行中，esc 可中断")
            return False
        if not self.agent:
            self._chat("system", "⚠ LLM 未配置或未就绪，无法执行任务")
            return False
        if not self.ctx or not self.ctx.tab:
            self._chat("system", "⚠ 浏览器未就绪")
            return False
        return True

    def _start_task(self, task_text: str) -> None:
        """进入忙碌态并启动任务 worker。"""
        self._set_busy(True)
        self._task_started = time.time()
        self._worker = self.run_worker(self._run_task(task_text), thread=False)

    async def _run_task(self, task_text: str) -> None:
        """任务 worker：执行 Agent 循环，异常与取消均转为用户可见。"""
        try:
            await self.agent.run(task_text)
        except asyncio.CancelledError:
            self.transcript().write_system("⏹ 已中断")
        except Exception as exc:  # noqa: BLE001 任务边界：失败必须可见
            self.logger.error("任务异常", exc_info=exc)
            self._chat("system", f"⚠ 任务异常中断: {type(exc).__name__}: {exc}")
        finally:
            self._set_busy(False)

    # ---- 忙碌态与浏览器窗口 ----
    def _set_busy(self, busy: bool) -> None:
        """切换忙碌态：状态栏、spinner、浏览器窗口显隐。"""
        self._busy = busy
        self.query_one("#hint", Static).update(
            Text("esc 中断任务", style=f"bold {ACCENT}") if busy else Text("? 快捷键 · ↑↓ 历史", style=GRAY)
        )
        if not busy:
            self.query_one("#spinner", Static).update("")
        self._set_window("normal" if busy else "minimized")

    def _set_window(self, state: str) -> None:
        """派发浏览器窗口显隐（委托 WindowScheduler）。Args: state 目标状态。"""
        self._window.set(state)

    def _tick_spinner(self) -> None:
        """定时推进 spinner 并刷新显示（仅忙碌时）。"""
        if not self._busy:
            return
        self.spinner.tick()
        self.query_one("#spinner", Static).update(self.spinner.render(self._task_started))

    # ---- 通道：命令路由与模态屏的调用面 ----
    def transcript(self) -> Transcript:
        """获取流水组件。"""
        return self.query_one("#transcript", Transcript)

    def _chat(self, role: str, text: str) -> None:
        """按角色写入流水。Args: role user/assistant/system; text 文本。"""
        t = self.transcript()
        if role == "user":
            t.write_user(text)
        elif role == "assistant":
            t.write_assistant(text)
        else:
            t.write_system(text)

    def set_status(self, text: str, error: bool = False) -> None:
        """更新右下状态栏。Args: text 文案; error 是否红色错误态。"""
        self.query_one("#info", Static).update(Text(text, style=f"bold {RED}" if error else f"dim {GRAY}"))

    def open_help(self) -> None:
        """打开快捷键帮助浮层。"""
        self.push_screen(HelpScreen())

    # LLM 配置应用见 tui.actions.LLMConfigActions（Mixin）

    def _welcome_cwd(self) -> str:
        """工作目录显示：主目录缩写为 ~。"""
        cwd = str(XIUMI_HOME)
        home = str(Path.home())
        return cwd.replace(home, "~", 1) if cwd.startswith(home) else cwd

    async def quick_shot(self) -> None:
        """手动截图当前页面到 screenshots 目录。"""
        try:
            path = self.config.screenshots_dir / f'manual_{time.strftime("%H%M%S")}.png'
            await self.ctx.tab.screenshot(path=path)
            self.transcript().write_tool_note(f"截图: {path}")
        except Exception as exc:  # noqa: BLE001 截图失败转为用户提示
            self._chat("system", f"截图失败: {exc}")
