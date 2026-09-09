"""模态屏：登录（终端内账密登录）、账密输入、短信验证码补输。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class LoginScreen(ModalScreen[bool]):
    """登录屏：账号密码在终端内完成，浏览器后台运行（滑块验证时自动弹出）。"""

    BINDINGS = [("escape", "skip", "跳过登录")]

    def compose(self) -> ComposeResult:
        with Vertical(id="login-box"):
            yield Label("尚未登录秀米", classes="login-title")
            yield Label("账号密码登录，全程在终端内完成（浏览器后台运行）：", classes="login-sub")
            yield Button("账号密码登录", id="btn-pwd", variant="default")
            yield Button("跳过（稍后再说）", id="btn-skip", variant="default")
            yield Static("", id="login-status")

    def on_mount(self) -> None:
        app = self.app
        app.bus.on("login_result", self._on_result)
        app.bus.on("sms_required", self._on_sms)
        app.bus.on("captcha_required", self._on_captcha)

    def on_unmount(self) -> None:
        app = self.app
        app.bus.off("login_result", self._on_result)
        app.bus.off("sms_required", self._on_sms)
        app.bus.off("captcha_required", self._on_captcha)

    def _status(self, text: str) -> None:
        self.query_one("#login-status", Static).update(text)

    def _disable(self) -> None:
        for b in self.query(Button):
            b.disabled = True

    def on_screen_resume(self) -> None:
        # 从账密屏返回时恢复按钮（此前 _disable 后无人恢复，导致登录屏卡死）
        for b in self.query(Button):
            b.disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-pwd":
            self._disable()
            self.app.push_screen(PasswordScreen())
        else:
            self.dismiss(False)

    def action_skip(self) -> None:
        self.dismiss(False)

    # ---- 事件 ----
    def _on_sms(self, _type: str, data: dict) -> None:
        self._status("页面要求短信验证码，请稍后在弹出的输入框填写…")

    def _on_captcha(self, _type: str, data: dict) -> None:
        self._status("🧩 需要滑块验证：浏览器窗口已自动弹出，请拖动完成后自动继续…")

    def _on_result(self, _type: str, data: dict) -> None:
        if data.get("ok"):
            self._status("✅ " + data.get("message", "登录成功"))
            self.dismiss(True)
        else:
            self._status("❌ " + data.get("message", "登录失败，可重试"))
            for b in self.query(Button):
                b.disabled = False


class PasswordScreen(ModalScreen[bool]):
    """账号密码输入（凭据只从这里直达登录插件，不进 LLM 上下文）。"""

    def compose(self) -> ComposeResult:
        with Vertical(id="pwd-box"):
            yield Label("账号密码登录秀米", classes="login-title")
            yield Input(placeholder="手机号 / 账号", id="acc")
            yield Input(placeholder="密码", id="pwd", password=True)
            yield Input(placeholder="短信验证码（如页面要求会提示填写）", id="sms")
            with Horizontal():
                yield Button("登录", id="btn-login", variant="primary")
                yield Button("提交验证码", id="btn-sms", variant="warning")
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
            self._status("提交中…（如页面要求短信验证码，填入第三栏后点「提交验证码」）")
            app.run_worker(app.actions["xiumi_login.password"](app.ctx, acc, pwd), exclusive=False)
        elif event.button.id == "btn-sms":
            sms = self.query_one("#sms", Input).value.strip()
            if not sms:
                self._status("请先在第三栏填写验证码")
                return
            app.actions["xiumi_login.sms_code"](sms)
            self._status("验证码已提交，等待登录结果…")
        else:
            self.dismiss(False)

    def _on_sms(self, _type: str, data: dict) -> None:
        self._status("⏳ 页面要求短信验证码：请查收短信，填入上方第三栏，然后点「提交验证码」")

    def _on_captcha(self, _type: str, data: dict) -> None:
        self._status("🧩 浏览器里弹出了滑块验证码：请到 Edge 窗口手动拖动完成，随后自动继续…")

    def _on_result(self, _type: str, data: dict) -> None:
        if data.get("ok"):
            self._status("✅ " + data.get("message", "登录成功"))
            self.dismiss(True)
        else:
            self._status("❌ " + data.get("message", "登录失败，可重试"))
