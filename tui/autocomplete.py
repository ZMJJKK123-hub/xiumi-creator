"""斜杠命令自动补全：命令系统的交互前置层。

架构定位：tui 表现层；上游 app.on_input_changed（刷新候选）与
on_input_submitted（Enter 决策）；候选数据复用 commands.COMMAND_INFO
（命令描述表单一事实源）；渲染写入 #suggest-box 面板。决策三态：
无参命令直接执行、带参命令补全待参、普通文本透传给任务流。

"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

from dataclasses import dataclass  # 决策 DTO

from rich.text import Text  # 候选列表渲染

from tui.theme import ACCENT, GRAY  # 主题色

# 带参数命令：Enter 只补全命令名与空格，等用户继续输参数；其余命令 Enter 直接执行
_PARAM_COMMANDS = {"/file"}


@dataclass
class SuggestDecision:
    """提交决策 DTO：补全控制器对 Enter 的裁决结果。

    类职责：强类型封装三态决策（消费与否/补全命令/原样透传）。
    属性：consumed 是否已消费；command 补全后的命令（可空）；passthrough 原文透传。
    生命周期：consume_submit 构造 → App 消费即弃。
    """
    """Enter 确定的决策结果。

    属性：consumed 是否已消费本次提交；command 待执行命令名（无参命令确定时非空）。
    """

    consumed: bool = False
    command: str = ""


class SuggestController:
    """斜杠命令补全控制器。

    类职责：按输入前缀过滤命令表、维护高亮位置、渲染候选面板、产出 Enter 决策。
    属性：_app 宿主（读 commands/transcript/query_one）；_items 当前候选；
    _index 高亮下标；_open 面板开关。
    生命周期：App 构造时创建；输入变化驱动；候选空或确定后关闭。
    """

    def __init__(self, app) -> None:
        """绑定宿主。

        Args: app 宿主应用（提供 commands 路由表与容器查询）。
        """
        self._app = app
        self._items: list[tuple[str, str]] = []
        self._index: int = 0
        self._open: bool = False

    # ---- 状态查询 ----
    @property
    def is_open(self) -> bool:
        """候选面板是否打开。Calls: 无。Args: None。Returns: bool。"""
        """候选面板是否打开。Args: None。Returns: bool。"""
        return self._open

    # ---- 输入驱动 ----
    def on_text(self, text: str) -> None:
        """输入变化刷新候选。Calls: _refresh。Args: text 输入框当前值。Returns: None。"""
        """按输入更新候选：以 / 开头则过滤显示，否则关闭。

        Args: text 输入框当前值。Returns: None。
        """
        text = text.strip()
        if not text.startswith("/"):
            self.close()
            return
        info = getattr(self._app.commands, "command_info", {})
        token = text.split(maxsplit=1)[0]
        self._items = [
            (name, desc) for name, desc in info.items() if name.startswith(token)
        ] if token != "/" else list(info.items())
        if not self._items:
            self.close()
            return
        self._index = min(self._index, len(self._items) - 1)
        self._open = True
        self._render()

    def step(self, delta: int) -> None:
        """Tab/Shift+Tab 循环切换候选。Calls: _render。Args: delta 步进方向。Returns: None。"""
        """Tab 循环移动高亮。

        Args: delta 步进（+1 下一个，-1 上一个）。Returns: None。
        """
        if not self._open:
            return
        self._index = (self._index + delta) % len(self._items)
        self._render()

    def close(self) -> None:
        """关闭候选面板。Calls: _hide。Args: None。Returns: None。"""
        """关闭面板并复位状态。Args: None。Returns: None。"""
        self._open = False
        self._items, self._index = [], 0
        self._set_box(None)

    # ---- Enter 决策 ----
    def consume_submit(self) -> SuggestDecision:
        """处理输入框提交：候选打开时确定当前高亮项。

        Globals Used: None。Calls: close / _hide。
        Args: None。Returns: SuggestDecision（consumed=True 表示已消费；
        command 非空表示应立即执行该命令）。
        """
        if not self._open or not self._items:
            return SuggestDecision()
        name = self._items[self._index][0]
        if name in _PARAM_COMMANDS:
            self._app.query_one("#task").value = f"{name} "
            self.close()
            return SuggestDecision(consumed=True)  # 填入命令名，等参数
        self.close()
        return SuggestDecision(consumed=True, command=name)  # 直接执行

    # ---- 渲染 ----
    def _render(self) -> None:
        """渲染候选列表到面板容器。Args: None。Returns: None。"""
        lines = Text()
        for i, (name, desc) in enumerate(self._items):
            active = i == self._index
            bg = " on #3a2a1f" if active else ""
            lines.append(f" {name:<10}", style=f"bold {ACCENT}{bg}" if active else f"bold {ACCENT}")
            lines.append(f"{desc}\n", style=f"white{bg}" if active else GRAY)
        self._set_box(lines)

    def _set_box(self, content: Text | None) -> None:
        """写入面板容器并切换显隐。

        Args: content 渲染内容，None 表示隐藏。Returns: None。
        """
        try:
            from textual.widgets import Static  # 局部导入：仅渲染用

            box = self._app.query_one("#suggest-box", Static)
            if content is None:
                box.display = False
            else:
                box.update(content)
                box.display = True
        except Exception as exc:  # noqa: BLE001 容器未就绪（启动早期）忽略渲染
            self._app.logger.debug("候选面板渲染跳过: %s", exc)
