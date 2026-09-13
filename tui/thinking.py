"""思考过程面板：内联于消息流的独立滚动思考视窗。

默认收起：思考进行时仅单行「✻ thinking Ns · ctrl+o 展开」实时跳秒，
想观看流式按 ctrl+o 原位展开 10 行视窗（文本连续追加，独立滚动），
思考结束收起为「✻ 思考了 Ns · ctrl+o 展开」。
"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

import time  # 轮次计时与刷新节流

from rich.text import Text  # 思考文本与状态行
from textual.app import ComposeResult  # 布局协议
from textual.containers import Vertical, VerticalScroll  # 面板与独立滚动视窗
from textual.widgets import Static  # 文本承载

from tui.theme import ACCENT, GRAY  # 主题色

# 刷新节流间隔（秒）：流式增量攒批渲染
REFRESH_S = 0.06


class ThinkingPanel(Vertical):
    """思考流面板：连续文本视窗 + 单行状态，按状态类切换形态。

    类职责：呈现思考流（默认收起单行，ctrl+o 展开 10 行独立滚动）。
    类变量：can_focus=False（焦点恒留输入框）。
    实例：_buf 全量思考文本；_last 上次刷新时间戳；_t0 轮次起点。
    生命周期：任务开始挂载进 Transcript；轮次驱动状态迁移，旧面板留存为收起行。
    """

    can_focus = False
    DEFAULT_CLASSES = "think-panel"

    def __init__(self) -> None:
        """初始化文本缓冲与计时（子部件引用在 on_mount 后可用）。"""
        super().__init__()
        self._buf = ""
        self._last = 0.0
        self._t0 = 0.0
        self._in_round = False  # 思考轮进行中（reset 判定用）
        self._scroll = None
        self._text = None
        self._status = None

    def compose(self) -> ComposeResult:
        """布局：独立滚动视窗（上）+ 单行状态（下，按状态显隐）。
        Globals Used: None。Calls: VerticalScroll/Static 构造。Args: None。Returns: 布局生成器。"""
        yield VerticalScroll(Static("", id="think-text"), id="think-scroll")
        yield Static("", id="think-status")

    def on_mount(self) -> None:
        """挂载后缓存子部件引用。Calls: query_one。Args: None。Returns: None。"""
        self._scroll = self.query_one("#think-scroll", VerticalScroll)
        self._text = self.query_one("#think-text", Static)
        self._status = self.query_one("#think-status", Static)
        self.border_title = " thinking "

    def _switch(self, state: str) -> None:
        """切换形态：移除全部状态类后挂目标类（CSS 控制显隐与高度）。
        Args: state 目标状态类名。Returns: None。"""
        for cls in ("collapsed", "expanded", "tall"):
            self.remove_class(cls)
        self.add_class(state)

    def begin_round(self) -> None:
        """新思考轮开始：默认收起为单行提示，想看流式再 ctrl+o 展开。
        Globals Used: None。Calls: _refresh / _switch。Args: None。Returns: None。"""
        self._t0 = time.time()
        self._buf = ""
        self._in_round = True
        self._refresh(pin=True)
        if self._status is not None:  # 挂载前仅累积，提示行挂载后由 reasoning 补写
            self._status.update(Text("✻ thinking · ctrl+o 展开", style=f"dim {ACCENT}"))
        self._switch("collapsed")

    def reasoning(self, delta: str) -> None:
        """思考增量连续累积；收起态下单行提示实时跳秒。
        Globals Used: None。Calls: _refresh。Args: delta 文本片。Returns: None。"""
        self._buf += delta
        if self._text is None:
            return  # 尚未挂载，仅累积
        now = time.monotonic()
        if now - self._last < REFRESH_S:
            return
        self._last = now
        self._refresh()
        if self._status is not None and self.has_class("collapsed"):
            elapsed = time.time() - self._t0
            self._status.update(
                Text(f"✻ thinking {elapsed:.0f}s · ctrl+o 展开", style=f"dim {ACCENT}")
            )

    def _refresh(self, pin: bool = False) -> None:
        """重绘思考文本；贴底（或强制）时滚动到最新内容。
        Args: pin 是否强制追尾。Returns: None。"""
        if self._text is None or self._scroll is None:
            return
        follow = pin or self._scroll.scroll_y >= self._scroll.max_scroll_y - 1
        self._text.update(Text(self._buf, style=GRAY))
        if follow:
            self._scroll.call_after_refresh(self._scroll.scroll_end, animate=False)

    def end_round(self, interrupted: bool = False) -> None:
        """思考轮结束：无思考内容则移除面板；否则收起为一行提示。
        Globals Used: None。Calls: _refresh / _remove_self / _switch。Args: interrupted 是否被中断。Returns: None。"""
        self._in_round = False
        if not self._buf.strip():
            import asyncio  # 局部导入：移除协程派发

            asyncio.get_running_loop().create_task(self._remove_self())  # 模型未思考：不留空面板
            return
        self._refresh(pin=True)
        if self._status is None:
            return
        word = "已中断" if interrupted else f"思考了 {time.time() - self._t0:.0f}s"
        self._status.update(
            Text(f"✻ {word} · ctrl+o 展开", style=GRAY if interrupted else f"dim {ACCENT}")
        )
        self._switch("collapsed")

    async def _remove_self(self) -> None:
        """从消息流中移除自身（无思考内容时调用）。Args: None。Returns: None。"""
        await self.remove()

    def toggle(self) -> None:
        """ctrl+o：收起 ⇄ 展开（展开后从头阅读；已移除的面板忽略）。
        Globals Used: None。Calls: _switch / scroll_home。Args: None。Returns: None。"""
        if self.parent is None:
            return
        if self.has_class("collapsed"):
            self._switch("expanded")
            self.add_class("tall")
            self._scroll.call_after_refresh(self._scroll.scroll_home, animate=False)
        elif self.has_class("expanded"):
            self._switch("collapsed")

    def reset(self) -> None:
        """任务终结：思考中被打断则改标为已中断，正常完成不覆盖。
        Globals Used: None。Calls: end_round。Args: None。Returns: None。"""
        if self._in_round:
            self.end_round(interrupted=True)


class ThinkingSink:
    """把 Agent 的流式思考回调适配到 ThinkingPanel（同事件循环直调）。

    类职责：轮次起止计时与面板驱动；正文不流式（完成后一次性呈现）。
    属性：_panel 目标面板；_t0 轮次起点。生命周期：任务开始构造，随任务结束
    属性：_panel 目标面板；_t0 轮次起点。
    """

    def __init__(self, panel: ThinkingPanel) -> None:
        """绑定面板。

        Args: panel 思考面板实例。
        """
        self._panel = panel
        self._t0 = 0.0

    def round_start(self) -> None:
        """轮次开始：面板进入流式形态。Calls: panel.begin_round。Args: None。Returns: None。"""
        self._panel.begin_round()

    def reasoning(self, delta: str) -> None:
        """思考增量转发。Calls: panel.reasoning。Args: delta 文本片。Returns: None。"""
        self._panel.reasoning(delta)

    def content(self, delta: str) -> None:
        """正文增量：按产品口径不流式，忽略。Calls: 无。Args: delta 文本片。Returns: None。"""

    def round_done(self) -> None:
        """轮次结束：面板收起为一行提示。Calls: panel.end_round。Args: None。Returns: None。"""
        self._panel.end_round()
