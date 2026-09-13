"""思考过程面板：流式展示 thinking 文本，独立滚动，完成后收起为一行提示。

状态机：HIDDEN（默认）→ STREAMING（流式，5 行视窗自动追尾）
→ COLLAPSED（一行提示）⇄ EXPANDED（ctrl+o，10 行视窗）。
独立滚动：内部 RichLog 悬停滚轮只滚本面板，不影响全局流水。
"""
from __future__ import annotations

import time  # 轮次计时

from rich.text import Text  # 状态行富文本
from textual.app import ComposeResult  # 布局协议
from textual.containers import Vertical  # 边框容器
from textual.widgets import RichLog, Static  # 滚动视窗与状态行

from tui.theme import ACCENT, BORDER_MUTED, GRAY  # 主题色

# 流式视窗行数 / 展开视窗行数
STREAM_LINES, EXPAND_LINES = 5, 10


class ThinkingPanel(Vertical):
    """思考流面板：可滚动思考视窗 + 状态行，按状态类切换形态。

    类变量：can_focus=False（焦点恒留输入框）。
    实例：_log 思考视窗；_status 单行提示；_t0 轮次起点；_seconds 思考耗时。
    生命周期：compose 创建于输入框上方；Agent 轮次驱动状态迁移。
    """

    can_focus = False
    DEFAULT_CLASSES = "hidden"

    def compose(self) -> ComposeResult:
        """布局：思考视窗（上）+ 状态行（下，按状态显隐）。"""
        yield RichLog(id="think-log", wrap=True, min_width=0, auto_scroll=True, markup=False)
        yield Static("", id="think-status")

    def on_mount(self) -> None:
        """挂载后缓存子部件引用与边框标题。"""
        self._log = self.query_one("#think-log", RichLog)
        self._status = self.query_one("#think-status", Static)
        self._t0 = 0.0
        self._seconds = 0.0
        self.border_title = " thinking "

    def _switch(self, state: str) -> None:
        """切换形态：移除全部状态类后挂目标类（CSS 控制显隐与高度）。"""
        for cls in ("hidden", "streaming", "collapsed", "expanded", "tall"):
            self.remove_class(cls)
        self.add_class(state)

    def begin_round(self) -> None:
        """新思考轮开始：清空视窗，进入流式形态。"""
        self._t0 = time.time()
        self._log.clear()
        self._switch("streaming")

    def reasoning(self, delta: str) -> None:
        """思考增量写入视窗（auto_scroll 自动追尾，滚动查看时不打扰）。"""
        self._log.write(delta, shrink=False, scroll_end=True)

    def end_round(self, interrupted: bool = False) -> None:
        """思考轮结束：收起为一行提示（记录耗时供展开展示）。"""
        self._seconds = time.time() - self._t0
        word = "已中断" if interrupted else f"思考了 {self._seconds:.0f}s"
        self._status.update(
            Text(f"✻ {word} · ctrl+o 展开", style=f"dim {ACCENT}" if not interrupted else GRAY)
        )
        self._switch("collapsed")

    def toggle(self) -> None:
        """ctrl+o：收起 ⇄ 展开（仅在有思考内容时生效）。"""
        if self.has_class("collapsed"):
            self._switch("expanded")
            self.add_class("tall")
        elif self.has_class("expanded"):
            self._switch("collapsed")

    def reset(self) -> None:
        """任务终结：保持收起提示（新任务 begin_round 时再清空）。"""
        if self.has_class("streaming"):
            self.end_round(interrupted=True)


class ThinkingSink:
    """把 Agent 的流式思考回调适配到 ThinkingPanel（同事件循环直调）。

    职责：轮次起止计时与面板驱动；正文不流式（完成后一次性呈现）。
    属性：_panel 目标面板；_t0 轮次起点。
    """

    def __init__(self, panel: ThinkingPanel) -> None:
        """绑定面板。

        Args: panel 思考面板实例。
        """
        self._panel = panel
        self._t0 = 0.0

    def round_start(self) -> None:
        """轮次开始：计时并让面板进入流式形态。"""
        self._t0 = time.time()
        self._panel.begin_round()

    def reasoning(self, delta: str) -> None:
        """思考增量转发。Args: delta 文本片。Returns: None。"""
        self._panel.reasoning(delta)

    def content(self, delta: str) -> None:
        """正文增量：按产品口径不流式，忽略。Args: delta 文本片。Returns: None。"""

    def round_done(self) -> None:
        """轮次结束：面板收起为一行提示。"""
        self._panel.end_round()
