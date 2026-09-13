"""主应用薄壳：布局组装与事件接线（boot/commands/theme/spinner 各自独立成模块）。"""
from __future__ import annotations

import asyncio  # _set_window 的异步任务派发
import time  # 任务计时与截图命名
from pathlib import Path  # 路径类型与插件目录定位

import plugins as _plugins_pkg  # 已安装的插件包：定位插件目录（源码/安装两态一致）
from rich.text import Text  # 状态栏富文本
from textual.binding import Binding  # 带优先级的键位绑定（Tab 补全需越过 Screen 默认焦点切换）
from textual.app import App, ComposeResult  # 应用基类与布局协议
from textual.css.query import NoMatches  # 拆除期部件查询异常（欢迎卡刷新兜底）
from textual.containers import Horizontal  # 输入框/状态栏横向容器
from textual.widgets import Input, Rule, Static  # 基础组件

from cdp.browser import EdgeBrowser  # 自动化浏览器生命周期
from core.config import Config, XIUMI_HOME, load_config  # 配置解析与数据目录
from core.events import Event, EventBus, EventType  # 强类型事件总线
from core.llm import LLMClient  # OpenAI 兼容客户端（apply_model 重建用）
from core.log import get_logger  # 统一日志
from core.registry import AppContext, PluginManager, ToolRegistry  # 插件体系
from tui.actions import LLMConfigActions, ShortcutActions  # 快捷键与 LLM 配置 Mixin
from tui.autocomplete import SuggestController  # 斜杠命令补全
from tui.boot import boot  # 启动编排
from tui.commands import CommandRouter  # 斜杠命令路由
from tui.screens import HelpScreen  # 帮助浮层
from tui.spinner import SpinnerState  # spinner 状态机
from tui.theme import ACCENT, APP_CSS  # 主题常量与全局 CSS
from tui.thinking import ThinkingPanel, ThinkingSink  # 思考流面板与回调适配
from tui.widgets import Transcript, WelcomeCard  # 常驻欢迎卡与流水（输入框用通用 Input）
from tui.window import WindowScheduler  # 浏览器窗口显隐

# 插件目录：从已安装包定位
PLUGINS_DIR = Path(_plugins_pkg.__file__).resolve().parent

# 任务总超时（秒）：LLM/工具单步各有超时，此为整任务兜底，防止无限转圈
TASK_TIMEOUT_S = 600

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
        ("ctrl+o", "toggle_thinking", "思考展开"),
        ("escape", "interrupt", "中断任务"),
        Binding("tab", "suggest_next", "下一候选", priority=True),
        Binding("shift+tab", "suggest_prev", "上一候选", priority=True),
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
        self.suggest = SuggestController(self)
        self._window = WindowScheduler(self)
        self.logger = get_logger("app")
        self._busy = False
        self._boot_failed = False
        self._worker = None
        self._task_started = 0.0
        self._think: ThinkingPanel | None = None  # on_mount 缓存引用
        self._tick_timer = None  # spinner 定时器（on_unmount 停表）

    def compose(self) -> ComposeResult:
        """布局：欢迎卡 / 流水 / 思考面板 / spinner / 候选面板 / 输入框 / 底栏。"""
        yield WelcomeCard()
        yield Transcript(id="transcript")
        yield ThinkingPanel(id="think-panel")
        yield Static("", id="spinner")
        yield Static("", id="suggest-box")
        yield Rule(id="rule-top")
        with Horizontal(id="input-box"):
            yield Static("> ", id="prompt-sym")
            yield Input(placeholder='Try "写一篇秋天咖啡店探店推文"', id="task")
        yield Rule(id="rule-bot")
        yield Horizontal(
            Static("", id="hint"),
            id="footer",
        )

    def on_mount(self) -> None:
        """挂载：聚焦输入框、接线事件、缓存思考面板引用、启动 boot。"""
        self._wire_events()
        self._think = self.query_one(ThinkingPanel)
        self.query_one("#task", Input).focus()
        self._tick_timer = self.set_interval(0.12, self._tick_spinner)
        self.run_worker(self._boot_task(), thread=False)

    def on_unmount(self) -> None:
        """拆除：停掉 spinner 定时器，避免部件卸载后回调查询。"""
        if self._tick_timer is not None:
            self._tick_timer.stop()

    async def _boot_task(self) -> None:
        """boot worker：调用 tui.boot 编排，取消仅记日志。"""
        try:
            await boot(self)
        except asyncio.CancelledError:
            self.logger.info("boot 被取消")

    def _wire_events(self) -> None:
        """订阅系统事件并映射到流水（状态类信息走流水，不占底栏）。"""
        bus, t = self.bus, self.transcript()
        bus.on(EventType.CHAT, lambda e: self._chat(e.role, e.text))
        bus.on(EventType.ACTION, lambda e: t.write_action(e.name, e.args))
        bus.on(EventType.TOOL_RESULT, lambda e: t.write_result(e.name, e.result))
        bus.on(EventType.SCREENSHOT, lambda e: t.write_tool_note(f"截图: {e.path}"))
        bus.on(EventType.ERROR, lambda e: t.write_system("⚠ " + e.message))
        bus.on(EventType.TASK_DONE, self._on_task_done)

    def _on_task_done(self, event: Event) -> None:
        """任务结束：解除忙碌并写统计行。"""
        self._set_busy(False)
        mark = "✻" if event.ok else "⚠"
        self.transcript().write_system(f"{mark} {event.message}")

    # ---- 用户输入 ----
    def on_input_changed(self, event: Input.Changed) -> None:
        """输入变化：主输入框以 / 开头时刷新候选。"""
        if len(self.screen_stack) == 1 and event.input.id == "task":
            self.suggest.on_text(event.value)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """提交处理：模态屏激活时不处理；候选打开时确定候选；
        否则回显命令条 → 命令路由 → 未消费则作为任务执行。"""
        if len(self.screen_stack) > 1:
            event.stop()
            return
        decision = self.suggest.consume_submit()
        if decision.consumed:
            event.stop()
            if decision.command:
                await self.commands.dispatch(self, decision.command)
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
        elif not (self.ctx and self.ctx.tab):
            self._chat("system", "⚠ 浏览器未就绪")
        else:
            return True
        return False

    def _start_task(self, task_text: str) -> None:
        """进入忙碌态并启动任务 worker（思考流接入思考面板）。"""
        self._set_busy(True)
        self._task_started = time.time()
        sink = ThinkingSink(self._think)
        self._worker = self.run_worker(self._run_task(task_text, sink), thread=False)

    async def _run_task(self, task_text: str, sink: ThinkingSink) -> None:
        """任务 worker：执行 Agent 循环（总超时兜底），异常与取消均转为用户可见。"""
        try:
            await asyncio.wait_for(self.agent.run(task_text, sink=sink), timeout=TASK_TIMEOUT_S)
        except asyncio.CancelledError:
            raise  # 中断提示由 esc 动作统一报告，避免双重输出
        except asyncio.TimeoutError:
            self._chat("system", f"⚠ 任务超时（{TASK_TIMEOUT_S // 60} 分钟），已终止")
        except Exception as exc:  # noqa: BLE001 任务边界：失败必须可见
            self.logger.error("任务异常", exc_info=exc)
            self._chat("system", f"⚠ 任务异常中断: {type(exc).__name__}: {exc}")
        finally:
            if self.is_running:  # 拆除期部件已销毁，跳过复位
                self._think.reset()
                self._set_busy(False)

    # ---- 忙碌态 ----
    def _set_busy(self, busy: bool) -> None:
        """切换忙碌态：底栏提示与 spinner（浏览器显隐由登录流程单独管理）。"""
        self._busy = busy
        self.query_one("#hint", Static).update(
            Text("esc 中断任务", style=f"bold {ACCENT}") if busy else Text("")
        )
        if not busy:
            self.query_one("#spinner", Static).update("")

    def _set_window(self, state: str) -> None:
        """派发浏览器窗口显隐（委托 WindowScheduler）。Args: state 目标状态。"""
        self._window.set(state)

    def _tick_spinner(self) -> None:
        """定时推进 spinner 并刷新显示（仅忙碌且运行中）。"""
        if not self._busy or not self.is_running:
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

    def open_help(self) -> None:
        """打开快捷键帮助浮层。"""
        self.push_screen(HelpScreen())

    def _welcome_model(self) -> str:
        """模型显示文案：未配好时提示未配置。"""
        return self.config.model if self.config.llm_ready else "未配置"

    def refresh_welcome(self) -> None:
        """刷新欢迎卡模型文案（boot 与配置屏保存后调用）。

        Args: None。Returns: None。Calls: WelcomeCard.set_model。
        """
        try:
            self.query_one(WelcomeCard).set_model(self._welcome_model())
        except NoMatches:  # 拆除期部件已销毁，无需刷新
            self.logger.debug("欢迎卡刷新跳过：部件不存在")

    async def quick_shot(self) -> None:
        """手动截图当前页面到 screenshots 目录。"""
        try:
            path = self.config.screenshots_dir / f'manual_{time.strftime("%H%M%S")}.png'
            await self.ctx.tab.screenshot(path=path)
            self.transcript().write_tool_note(f"截图: {path}")
        except Exception as exc:  # noqa: BLE001 截图失败转为用户提示
            self._chat("system", f"截图失败: {exc}")
