"""模态屏：账密登录（/login 打开）、短信验证码补输。键盘操作：Tab 切换，Enter 确认。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class PasswordScreen(ModalScreen[bool]):
    """账密登录屏：凭据直达登录插件执行，不进 LLM 上下文。"""

    def compose(self) -> ComposeResult:
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
        self.app.bus.on("login_result", self._on_result)
        self.app.bus.on("sms_required", self._on_sms)
        self.app.bus.on("captcha_required", self._on_captcha)
        self.query_one("#acc", Input).focus()

    def on_unmount(self) -> None:
        self.app.bus.off("login_result", self._on_result)
        self.app.bus.off("sms_required", self._on_sms)
        self.app.bus.off("captcha_required", self._on_captcha)

    def _status(self, text: str) -> None:
        self.query_one("#pwd-status", Static).update(text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
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

    def _on_sms(self, _type: str, data: dict) -> None:
        self._status("需要短信验证码，查收后填入并点提交验证码")

    def _on_captcha(self, _type: str, data: dict) -> None:
        self._status("需要滑块验证，浏览器窗口已弹出，完成后自动继续")

    def _on_result(self, _type: str, data: dict) -> None:
        if data.get("ok"):
            self._status("登录成功")
            self.dismiss(True)
        else:
            self._status(data.get("message", "登录失败，可重试"))
