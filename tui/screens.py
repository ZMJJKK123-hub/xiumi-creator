"""模态屏家族：账密登录屏（/login 打开）与快捷键帮助浮层。

Rule2 §1 表现层：凭据经事件直达登录插件，不进 LLM 上下文。
"""
from __future__ import annotations

from rich.text import Text  # 帮助浮层的富文本构建
from textual.app import ComposeResult  # 布局协议
from textual.containers import Horizontal, Vertical  # 容器
from textual.screen import ModalScreen  # 模态屏基类
from textual.widgets import Button, Input, Label, Static  # 基础组件

from core.events import Event, EventType  # 强类型事件
from tui.theme import ACCENT, GRAY  # 主题色


class PasswordScreen(ModalScreen[bool]):
    """账密登录屏。

    类职责：收集账号/密码/验证码并调用登录动作；展示登录过程事件。
    实例：无自定义状态，输入值即取即用。
    生命周期：/login 命令打开 → 登录成功 dismiss(True) 或返回 dismiss(False)。
    """

    def compose(self) -> ComposeResult:
        """布局：标题 + 三输入框 + 三按钮 + 状态行。"""
        with Vertical(id="pwd-box"):
            yield Label("登录秀米", classes="login-title")
            yield Label("Tab 切换，Enter 确认", classes="login-sub")
            yield Input(placeholder="手机号或邮箱", id="acc")
            yield Input(placeholder="密码", id="pwd", password=True)
            yield Input(placeholder="短信验证码，收到后填这里", id="sms")
            with Horizontal():
                yield Button("登录", id="btn-login", variant="default")
                yield Button("提交验证码", id="btn-sms", variant="default")
                yield Button("返回", id="btn-back", variant="default")
            yield Static("", id="pwd-status")

    def on_mount(self) -> None:
        """挂载：订阅登录事件并聚焦账号框。"""
        self.app.bus.on(EventType.LOGIN_RESULT, self._on_result)
        self.app.bus.on(EventType.SMS_REQUIRED, self._on_sms)
        self.app.bus.on(EventType.CAPTCHA_REQUIRED, self._on_captcha)
        self.query_one("#acc", Input).focus()

    def on_unmount(self) -> None:
        """卸载：退订事件，避免悬挂订阅。"""
        self.app.bus.off(EventType.LOGIN_RESULT, self._on_result)
        self.app.bus.off(EventType.SMS_REQUIRED, self._on_sms)
        self.app.bus.off(EventType.CAPTCHA_REQUIRED, self._on_captcha)

    def _status(self, text: str) -> None:
        """更新屏内状态行。

        Args: text 状态文案。Returns: None。
        """
        self.query_one("#pwd-status", Static).update(text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮分发：登录提交 / 验证码提交 / 返回。

        Args: event 按钮事件。Calls: app.actions 中的登录动作。
        """
        app = self.app
        if event.button.id == "btn-login":
            acc = self.query_one("#acc", Input).value.strip()
            pwd = self.query_one("#pwd", Input).value
            if not acc or not pwd:
                self._status("请填写账号和密码")
                return
            self._status("提交中")
            app.run_worker(app.actions["xiumi_login.password"](app.ctx, acc, pwd), exclusive=False)
        elif event.button.id == "btn-sms":
            sms = self.query_one("#sms", Input).value.strip()
            if not sms:
                self._status("请先填写验证码")
                return
            app.actions["xiumi_login.sms_code"](sms)
            self._status("验证码已提交，等待结果")
        else:
            self.dismiss(False)

    def _on_sms(self, event: Event) -> None:
        """短信验证码要求提示。Args: event SMS_REQUIRED 事件。"""
        self._status("需要短信验证码，查收后填入并点提交验证码")

    def _on_captcha(self, event: Event) -> None:
        """滑块验证要求提示。Args: event CAPTCHA_REQUIRED 事件。"""
        self._status("需要滑块验证，浏览器窗口已弹出，完成后自动继续")

    def _on_result(self, event: Event) -> None:
        """登录结果：成功关屏，失败保留重试。Args: event LOGIN_RESULT 事件。"""
        if event.ok:
            self._status("登录成功")
            self.dismiss(True)
        else:
            self._status(event.message or "登录失败，可重试")


class HelpScreen(ModalScreen[None]):
    """快捷键帮助浮层：任意键关闭。

    类职责：展示键位与命令速查。
    生命周期：? 或 /help 打开 → 任意键 dismiss(None)。
    """

    def compose(self) -> ComposeResult:
        """布局：橙标题 + 键位两列文本。"""
        rows = [
            ("?        ", "帮助，任意键关闭"),
            ("esc      ", "中断当前任务"),
            ("↑ / ↓    ", "翻阅输入历史"),
            ("PgUp/PgDn", "翻看历史消息"),
            ("ctrl+l   ", "清屏"),
            ("ctrl+q   ", "退出"),
            ("/model 名称", "设置模型"),
            ("/file 路径", "载入任务文件，支持 [img:路径]"),
            ("/login   ", "登录"),
            ("/shot    ", "截图"),
        ]
        content = Text()
        content.append("快捷键 / 命令\n\n", style=f"bold {ACCENT}")
        for key, desc in rows:
            content.append(f"{key}  ", style=f"bold {ACCENT}")
            content.append(desc + "\n", style=GRAY)
        yield Static(content, id="help-box")

    def on_key(self, event) -> None:
        """任意键关闭浮层。Args: event 按键事件。"""
        self.dismiss(None)
