"""模态屏家族：覆盖在主屏之上的两个浮层。

架构定位：tui 表现层；由 commands 路由（/model、/help）push_screen 打开。
ModelConfigScreen 是配置写入口：保存经 core.config.persist_env 落 .env、
经 actions.apply_* 即席重建 Agent——是 TUI 触达 core 配置层的唯一界面。
"""

from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

from rich.text import Text  # 帮助浮层的富文本构建
from textual.app import ComposeResult  # 布局协议
from textual.containers import Horizontal, Vertical  # 容器
from textual.screen import ModalScreen  # 模态屏基类
from textual.widgets import Button, Input, Label, Static  # 基础组件

from tui.theme import ACCENT, GRAY  # 主题色


class HelpScreen(ModalScreen[None]):
    """快捷键帮助浮层：任意键关闭。

    类职责：展示键位与命令速查。
    属性：无实例状态（compose 即渲染）。
    生命周期：/help 打开 → 任意键 dismiss(None)。
    """

    def compose(self) -> ComposeResult:
        """布局：橙标题 + 键位两列文本。Calls: Static 构造。Args: None。Returns: 布局生成器。"""
        rows = [
            ("/model", "配置模型、API Key、接口地址"),
            ("/file 路径", "载入任务文件，支持 [img:路径]"),
            ("/login", "登录秀米"),
            ("/shot", "截图"),
            ("/help", "帮助，任意键关闭"),
            ("esc", "中断任务"),
            ("PgUp/PgDn", "翻看消息"),
            ("ctrl+o", "思考过程展开/收起"),
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
        """任意键关闭浮层。Calls: dismiss。Args: event 按键事件。Returns: None。"""
        self.dismiss(None)


class ModelConfigScreen(ModalScreen[bool]):
    """模型配置屏：三项 LLM 配置同屏填写保存；/model 打开，保存/取消后 dismiss。

    类职责：收集 LLM 三要素并持久化（凭据不进对话上下文）。
    属性：无实例状态（保存即退出）。
    生命周期：/model 打开 → Enter 保存 dismiss(True) / 取消 dismiss(False)。
    """

    def compose(self) -> ComposeResult:
        """布局：标题 + 三输入框（模型/Key/URL）+ 保存取消按钮 + 状态行。
        Calls: Input/Button/Static 构造。Args: None。Returns: 布局生成器。"""
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
        """挂载：聚焦模型框。Globals Used: None。Calls: focus。Args: None。Returns: None。"""
        self.query_one("#cfg-model", Input).focus()

    def _status(self, text: str) -> None:
        """更新屏内状态行。Args: text 状态文案。Returns: None。"""
        self.query_one("#cfg-status", Static).update(text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter 在三输入框间流转，末框保存。Calls: focus / _save / dismiss。Args: event 提交事件。Returns: None。"""
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
        """保存非空项到 .env 并刷新 Agent。

        Globals Used: None。Calls: persist_env / apply_llm_config / apply_model / refresh_welcome。
        Args: None。Returns: None。
        """
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
        app.refresh_welcome()
        if not saved:
            self._status("未填写任何项")
            return
        self._status("已保存：" + "、".join(saved))
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮分发：保存 / 取消。Calls: _save / dismiss。Args: event 按钮事件。Returns: None。"""
        if event.button.id == "btn-save":
            self._save()
        else:
            self.dismiss(False)
