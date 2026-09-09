"""Textual 主应用：按项目 UI 规格书实现的 Claude Code 风格终端界面（核心逻辑不变）。

布局（规格 §2）：
A 欢迎头部卡片（橙色圆角、双栏）  B 交互流水（用户命令条 + └ 树）
C 底部输入框（上下 ─ 细线包裹 `> ` 提示行）  D 状态栏（左：随状态切换提示 / 右：系统状态与诊断）
spinner：帧序列 · ✢ ✳ ✶ ✻ ✽ + 动名词 + (Ns)，下方 └ Tip 提示
浏览器可见性：登录/待命后台最小化；任务运行与滑块验证时自动弹出。
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Input, Rule, Static

from cdp.browser import EdgeBrowser
from core.agent import Agent
from core.config import Config, XIUMI_HOME, load_config
from core.events import EventBus
from core.llm import LLMClient
from core.registry import AppContext, PluginManager, ToolRegistry
from tui.screens import LoginScreen
from tui.widgets import ACCENT, GRAY, RED, TaskInput, Transcript

# 插件目录取自已安装的 plugins 包（dev 与 pip 安装模式都正确）
import plugins as _plugins_pkg

PLUGINS_DIR = Path(_plugins_pkg.__file__).resolve().parent

SPINNER_FRAMES = ["·", "✢", "✳", "✶", "✻", "✽"]
# 取自 Claude Code 实际使用的 spinner 动名词表（节选）
SPINNER_VERBS = [
    "Pondering", "Mulling", "Simmering", "Marinating", "Noodling", "Vibing",
    "Rethinking", "Synthesizing", "Musing", "Stewing", "Spinning", "Wandering",
    "Brewing", "Whisking", "Seasoning", "Proofing", "Mustering", "Meandering",
    "Baking", "Percolating",
]
BUSY_TIP = "└ Tip: esc 中断当前任务，已完成的步骤不会回滚"


class HelpScreen(ModalScreen[None]):
    """? 快捷键帮助浮层（任意键关闭）。"""

    def compose(self) -> ComposeResult:
        content = Text()
        content.append("快捷键 / 命令\n\n", style=f"bold {ACCENT}")
        rows = [
            ("?        ", "打开本帮助（任意键关闭）"),
            ("esc      ", "中断当前任务"),
            ("↑ / ↓    ", "翻阅输入历史"),
            ("ctrl+l   ", "清屏"),
            ("ctrl+q   ", "退出"),
            ("/file 路径", "载入任务文件（支持 [img:路径] 标记）"),
            ("/login   ", "打开登录窗口"),
            ("/shot    ", "截取当前页面"),
        ]
        for key, desc in rows:
            content.append(f"{key}  ", style=f"bold {ACCENT}")
            content.append(desc + "\n", style=GRAY)
        yield Static(content, id="help-box")

    def on_key(self, _event) -> None:
        self.dismiss(None)


class XiumiAgentApp(App):
    CSS = f"""
    Screen {{ background: #0C0C0C; }}
    #transcript {{
        height: 1fr; padding: 0 1; background: transparent;
        scrollbar-background: #101010;
        scrollbar-background-hover: #161616;
        scrollbar-color: #3a3a3f;
        scrollbar-color-hover: {ACCENT};
        scrollbar-size: 1 1;
    }}
    #spinner {{ height: auto; padding: 0 1; }}
    #rule-top, #rule-bot {{ color: {GRAY}; margin: 0 1; }}
    #input-box {{ height: auto; padding: 0 1; }}
    #prompt-sym {{ width: auto; color: {GRAY}; padding: 0 0 0 1; }}
    #task {{ border: none; background: transparent; height: 1; padding: 0; }}
    #task:focus {{ background-tint: transparent; }}
    #footer {{ height: 1; padding: 0 2; }}
    #hint {{ width: auto; height: 1; color: {GRAY}; }}
    #info {{ width: 1fr; height: 1; overflow: hidden; text-align: right; color: {GRAY}; }}
    #help-box {{ border: round {ACCENT}; background: #161616; padding: 1 2; margin: 4 12; width: 76; }}
    LoginScreen, PasswordScreen {{ align: center middle; }}
    #login-box, #pwd-box {{ width: 64; height: auto; border: round #4a4a52; background: #161616; padding: 1 2; }}
    #login-box Button, #pwd-box Button {{
        width: 100%; margin-bottom: 1; background: #1f1f1f; color: #e8e8e8;
        border: round #4a4a52; text-style: none;
    }}
    #login-box Button:hover, #pwd-box Button:hover, #login-box Button:focus, #pwd-box Button:focus {{
        border: round {ACCENT}; background: #262626;
    }}
    #acc, #pwd, #sms {{ border: tall #4a4a52; background: #101010; }}
    #acc:focus, #pwd:focus, #sms:focus {{ border: tall {ACCENT}; }}
    #pwd-box Horizontal {{ height: auto; }}
    #pwd-box Horizontal Button {{ width: 1fr; }}
    .login-title {{ text-style: bold; color: {ACCENT}; }}
    .login-sub {{ color: {GRAY}; margin-bottom: 1; }}
    """

    BINDINGS = [
        ("ctrl+q", "quit", "退出"),
        ("ctrl+l", "clear_logs", "清屏"),
        ("escape", "interrupt", "中断任务"),
        ("question_mark", "help", "帮助"),
        ("up", "history_prev", "上一条输入"),
        ("down", "history_next", "下一条输入"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config: Config | None = None
        self.bus = EventBus()
        self.ctx: AppContext | None = None
        self.registry = ToolRegistry()
        self.plugins = PluginManager(PLUGINS_DIR, self.registry)
        self.agent: Agent | None = None
        self.browser: EdgeBrowser | None = None
        self.actions: dict = {}
        self._busy = False
        self._boot_failed = False
        self._worker = None
        # spinner 状态
        self._spin_frame = 0
        self._spin_verb = 0
        self._task_started = 0.0
        # 输入历史
        self._history: list[str] = []
        self._hist_idx: int | None = None
        self._draft: str = ""

    # ---- 布局：B 流水 / spinner / C 输入框（─ 细线包裹）/ D 状态栏 ----
    def compose(self) -> ComposeResult:
        yield Transcript(id="transcript")
        yield Static("", id="spinner")
        yield Rule(id="rule-top")
        with Horizontal(id="input-box"):
            yield Static("> ", id="prompt-sym")
            yield TaskInput(
                placeholder="Try \"写一篇秋天咖啡店探店推文，主色暖棕\"", id="task", compact=True
            )
        yield Rule(id="rule-bot")
        yield Horizontal(
            Static("? 快捷键 · ↑↓ 历史", id="hint"),
            Static("", id="info"),
            id="footer",
        )

    def on_mount(self) -> None:
        self._wire_events()
        self.set_status("启动中…")
        self.set_interval(0.12, self._tick_spinner)
        self.run_worker(self._boot(), thread=False)

    # ---- 启动（核心逻辑不变）----
    async def _boot(self) -> None:
        self.config = load_config()
        # A 欢迎头部卡片（需要 model 与 cwd）
        self.query_one("#transcript", Transcript).write_welcome(
            model=self._welcome_model(),
            cwd=self._welcome_cwd(),
        )
        if not self.config.llm_ready:
            self._chat("system", "⚠ 未配置 LLM（.env 缺少 OPENAI_API_KEY）。浏览器与登录功能可用，但无法执行任务。")
        self.set_status("启动 Edge…")
        try:
            self.browser = EdgeBrowser(self.config)
            await self.browser.ensure_started(start_url="https://xiumi.us/")
            await self.browser.connect()
            self.ctx = AppContext(self.config, self.bus)
            self.ctx.cdp = self.browser.cdp
            self.ctx.tab = await self.browser.get_or_create_tab("xiumi.us", "https://xiumi.us/")
            await self.plugins.load_all(self.ctx)
            self.actions = self.plugins.actions
        except Exception as e:
            self._boot_failed = True
            self.set_status(f"启动失败: {e}", error=True)
            self._chat("system", f"⚠ 浏览器/插件启动失败: {e}")
            return

        if self.config.llm_ready:
            self.agent = Agent(self.ctx, self.registry, LLMClient(self.config), self.bus)
        self.set_status(f"{self.config.model} · {len(self.registry.names())} tools")

        try:
            logged_in = await self.actions["xiumi_login.check"]()
        except Exception:
            logged_in = False
        if not logged_in:
            self.push_screen(LoginScreen())
        else:
            self.set_status(f"{self.config.model} · 秀米已登录")
            self._chat("system", "✻ 就绪，输入任务开始。")

    # ---- 事件总线 → 流水 ----
    def _wire_events(self) -> None:
        t = self.query_one("#transcript", Transcript)
        self.bus.on("chat", lambda et, d: self._chat(d["role"], d["text"]))
        self.bus.on("action", lambda et, d: t.write_action(d["name"], d["args"]))
        self.bus.on("tool_result", lambda et, d: t.write_result(d["name"], d["result"]))
        self.bus.on("status", lambda et, d: self.set_status(d["text"]))
        self.bus.on("screenshot", lambda et, d: t.write_tool_note(f"截图: {d['path']}"))
        self.bus.on("error", lambda et, d: t.write_system("⚠ " + d["message"]))
        self.bus.on("captcha_required", lambda et, d: self._set_window("normal"))  # 滑块需人工，弹出浏览器

        def _login_done(et: str, d: dict) -> None:
            if d.get("ok"):
                self._set_window("minimized")  # 登录完成收回后台

        self.bus.on("login_result", _login_done)

        def _done(et: str, d: dict) -> None:
            self._set_busy(False)
            mark = "✻" if d.get("ok") else "⚠"
            t.write_system(f"{mark} {d.get('message', '')}")
        self.bus.on("task_done", _done)

    def _chat(self, role: str, text: str) -> None:
        t = self.query_one("#transcript", Transcript)
        if role == "user":
            t.write_user(text)
        elif role == "assistant":
            t.write_assistant(text)
        else:
            t.write_system(text)

    # ---- 浏览器可见性调度（后台运行，必要时弹出）----
    def _set_window(self, state: str) -> None:
        async def _go() -> None:
            try:
                if self.browser and self.ctx and self.ctx.tab:
                    await self.browser.set_window_state(self.ctx.tab, state)
            except Exception:
                pass

        try:
            asyncio.get_running_loop().create_task(_go())
        except RuntimeError:
            pass

    # ---- D 状态栏 ----
    def set_status(self, text: str, error: bool = False) -> None:
        self.query_one("#info", Static).update(Text(text, style=f"bold {RED}" if error else f"dim {GRAY}"))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.query_one("#hint", Static).update(
            Text("esc 中断任务", style=f"bold {ACCENT}") if busy else Text("? 快捷键 · ↑↓ 历史", style=GRAY)
        )
        if not busy:
            self.query_one("#spinner", Static).update("")
        # 任务运行时弹出浏览器供观看，结束后收回后台
        self._set_window("normal" if busy else "minimized")

    # ---- spinner（· Infusing... (35s) + └ Tip）----
    def _tick_spinner(self) -> None:
        if not self._busy:
            return
        self._spin_frame = (self._spin_frame + 1) % len(SPINNER_FRAMES)
        if self._spin_frame == 0:
            self._spin_verb = (self._spin_verb + 1) % len(SPINNER_VERBS)
        elapsed = int(time.time() - self._task_started)
        t = Text(SPINNER_FRAMES[self._spin_frame] + " ", style=f"bold {ACCENT}")
        t.append(f"{SPINNER_VERBS[self._spin_verb]}... ", style="white")
        t.append(f"({elapsed}s)", style=GRAY)
        t.append("\n")
        t.append(BUSY_TIP, style=f"dim {GRAY}")
        self.query_one("#spinner", Static).update(t)

    # ---- 用户输入（命令与任务逻辑不变）----
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        if not raw:
            event.input.value = ""  # 纯空白提交：清空残留空格，不产生任何输出
            return
        event.input.value = ""
        self._history.append(raw)
        self._hist_idx = None
        transcript = self.query_one("#transcript", Transcript)
        transcript.write_user(raw)  # 所有输入（含本地命令）都先回显用户命令条

        if raw == "/login":
            if self.actions:
                self.push_screen(LoginScreen())
            else:
                self._chat("system", "插件尚未就绪，稍等片刻再试")
            return
        if raw in ("/help", "?"):
            self.push_screen(HelpScreen())
            return
        if raw == "/shot":
            if self.ctx and self.ctx.tab:
                self.run_worker(self._quick_shot(), thread=False)
            else:
                self._chat("system", "浏览器尚未就绪，无法截图")
            return
        if raw.startswith("/file"):
            parts = raw.split(maxsplit=1)
            if len(parts) < 2:
                self._chat("system", "用法: /file 路径/到/task.md")
                return
            path = Path(parts[1].strip('"'))
            if not path.exists():
                self._chat("system", f"⚠ 文件不存在: {path}")
                return
            raw = path.read_text(encoding="utf-8")
            transcript.write_user(raw)  # 回显展开后的任务内容
            self._chat("system", f"已载入 {path}（{len(raw)} 字符）")

        if self._busy:
            self._chat("system", "⏳ 上一轮任务还在进行中（esc 可中断）")
            return
        if not self.agent:
            self._chat("system", "⚠ LLM 未配置或未就绪，无法执行任务")
            return
        if not self.ctx or not self.ctx.tab:
            self._chat("system", "⚠ 浏览器未就绪")
            return

        self._set_busy(True)
        self._task_started = time.time()
        self._worker = self.run_worker(self._run_task(raw), thread=False)

    async def _run_task(self, task: str) -> None:
        try:
            await self.agent.run(task)
        except Exception as e:
            if "CancelledError" in type(e).__name__:
                self.query_one("#transcript", Transcript).write_system("⏹ 已中断")
            else:
                self._chat("system", f"⚠ 任务异常中断: {type(e).__name__}: {e}")
        finally:
            self._set_busy(False)

    async def _quick_shot(self) -> None:
        try:
            path = self.config.screenshots_dir / f"manual_{time.strftime('%H%M%S')}.png"
            await self.ctx.tab.screenshot(path=path)
            self.query_one("#transcript", Transcript).write_tool_note(f"截图: {path}")
        except Exception as e:
            self._chat("system", f"截图失败: {e}")

    # ---- 快捷键动作 ----
    def action_interrupt(self) -> None:
        if self._busy and self._worker is not None:
            self._worker.cancel()
            self._set_busy(False)
            self.query_one("#transcript", Transcript).write_system("⏹ 已中断（esc）")

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def _welcome_model(self) -> str:
        """欢迎卡元信息的模型文案（首启/清屏保持一致）。"""
        if self.config and self.config.llm_ready:
            return self.config.model
        return "未配置"

    def _welcome_cwd(self) -> str:
        """工作目录显示（用户主目录缩写为 ~，避免长路径难看地折行）。"""
        cwd = str(XIUMI_HOME)
        home = str(Path.home())
        return cwd.replace(home, "~", 1) if cwd.startswith(home) else cwd

    def action_clear_logs(self) -> None:
        t = self.query_one("#transcript", Transcript)
        t.clear()
        t.write_welcome(model=self._welcome_model(), cwd=self._welcome_cwd())

    def action_history_prev(self) -> None:
        if not self._history:
            return
        inp = self.query_one("#task", Input)
        if self._hist_idx is None:
            self._draft = inp.value
            self._hist_idx = len(self._history) - 1
        elif self._hist_idx > 0:
            self._hist_idx -= 1
        inp.value = self._history[self._hist_idx]
        inp.cursor_position = len(inp.value)  # 光标落末尾，避免选中态渲染异常

    def action_history_next(self) -> None:
        if self._hist_idx is None:
            return
        inp = self.query_one("#task", Input)
        if self._hist_idx < len(self._history) - 1:
            self._hist_idx += 1
            inp.value = self._history[self._hist_idx]
        else:
            self._hist_idx = None
            inp.value = self._draft
        inp.cursor_position = len(inp.value)
