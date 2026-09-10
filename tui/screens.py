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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """输入框内 Enter：账号框跳密码框，密码框直接提交登录。

        必须 stop 阻止冒泡——否则事件会到达主 App 的任务处理器，
        把输入框内容当作任务文本发给 LLM（凭据泄露）。
        Args: event 输入提交事件。Returns: None。
        """
        event.stop()
        if event.input.id == "acc":
            self.query_one("#pwd", Input).focus()
            return
        if event.input.id == "pwd":
            self._submit_login()

    def _submit_login(self) -> None:
        """校验并提交账号密码；登录 worker 的异常转为屏内提示，不让应用崩溃。"""
        app = self.app
        acc = self.query_one("#acc", Input).value.strip()
        pwd = self.query_one("#pwd", Input).value
        if not acc or not pwd:
            self._status("请填写账号和密码")
            return
        self._status("提交中")

        async def _run_login() -> None:
            """登录 worker 包装：捕获异常显示在状态行。"""
            try:
                await app.actions["xiumi_login.password"](app.ctx, acc, pwd)
            except Exception as exc:  # noqa: BLE001 登录失败必须可见且不崩应用
                self._status(f"登录失败: {exc}")
            else:
                self._status("登录流程结束")

        app.run_worker(_run_login(), exclusive=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮分发：登录提交 / 验证码提交 / 返回。

        Args: event 按钮事件。Calls: app.actions 中的登录动作。
        """
        app = self.app
        if event.button.id == "btn-login":
            self._submit_login()
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
            ("/model", "配置模型、API Key、接口地址"),
            ("/file 路径", "载入任务文件，支持 [img:路径]"),
            ("/login", "登录秀米"),
            ("/shot", "截图"),
            ("/help", "帮助，任意键关闭"),
            ("esc", "中断任务"),
            ("PgUp/PgDn", "翻看消息"),
            ("ctrl+l", "清屏"),
            ("ctrl+q", "退出"),
        ]
        content = Text()
        content.append("命令 / 快捷键\n\n", style=f"bold {ACCENT}")
        for key, desc in rows:
            content.append(f"{key:<10}", style=f"bold {ACCENT}")
            content.append(desc + "\n", style=GRAY)
        yield Static(content, id="help-box")

    def on_key(self, event) -> None:
        """任意键关闭浮层。Args: event 按键事件。"""
        self.dismiss(None)


class ModelConfigScreen(ModalScreen[bool]):
    """模型配置屏：三项 LLM 配置同屏填写保存；/model 打开，保存/取消后 dismiss。"""

    def compose(self) -> ComposeResult:
        """布局：标题 + 三输入框（模型/Key/URL）+ 保存取消按钮 + 状态行。"""
        with Vertical(id="cfg-box"):
            yield Label("模型配置", classes="login-title")
            yield Label("Tab 切换，Enter 下一项", classes="login-sub")
            yield Input(placeholder="模型名，如 deepseek-chat", id="cfg-model")
            yield Input(placeholder="API Key", id="cfg-key", password=True)
            yield Input(placeholder="接口地址，如 https://open.bigmodel.cn/api/paas/v4", id="cfg-url")
            with Horizontal():
                yield Button("保存", id="btn-save", variant="default")
                yield Button("取消", id="btn-cancel", variant="default")
            yield Static("", id="cfg-status")

    def on_mount(self) -> None:
        """挂载：聚焦模型框。"""
        self.query_one("#cfg-model", Input).focus()

    def _status(self, text: str) -> None:
        """更新屏内状态行。Args: text 状态文案。Returns: None。"""
        self.query_one("#cfg-status", Static).update(text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter 流转：模型→Key→URL→保存；stop 防冒泡成任务。

        Args: event 输入提交事件。Returns: None。
        """
        event.stop()
        order = ["cfg-model", "cfg-key", "cfg-url"]
        if event.input.id not in order:
            return
        idx = order.index(event.input.id)
        if idx < len(order) - 1:
            self.query_one(f"#{order[idx + 1]}", Input).focus()
        else:
            self._save()

    def _save(self) -> None:
        """保存非空项到 .env 并刷新 Agent。Calls: persist_env / apply_llm_config / apply_model。"""
        from core.config import persist_env  # 局部导入：配置持久化

        app = self.app
        model = self.query_one("#cfg-model", Input).value.strip()
        key = self.query_one("#cfg-key", Input).value.strip()
        url = self.query_one("#cfg-url", Input).value.strip().rstrip("/")
        saved: list[str] = []
        try:
            if model:
                persist_env("MODEL", model)
                saved.append("模型")
            if key:
                persist_env("OPENAI_API_KEY", key)
                saved.append("Key")
            if url:
                if not url.startswith(("http://", "https://")):
                    self._status("接口地址需以 http:// 或 https:// 开头")
                    return
                persist_env("OPENAI_BASE_URL", url)
                saved.append("地址")
        except Exception as exc:  # noqa: BLE001 保存失败必须可见
            self._status(f"保存失败: {exc}")
            return
        if key:
            app.apply_llm_config(api_key=key)
        if url:
            app.apply_llm_config(base_url=url)
        if model:
            app.apply_model(model)
        else:
            app._refresh_agent()
        if not saved:
            self._status("未填写任何项")
            return
        self._status("已保存：" + "、".join(saved))
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮分发：保存 / 取消。Args: event 按钮事件。"""
        if event.button.id == "btn-save":
            self._save()
        else:
            self.dismiss(False)
