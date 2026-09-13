"""终端组件：常驻欢迎卡、任务输入框与对话流水渲染器。

Rule2 §1 表现层组件；颜色常量在 theme，纯算法在 textutils，
欢迎卡内容构建在 welcome——本文件只保留组件本身。
"""
from __future__ import annotations

import re  # 助手回复按空行分段

from rich.text import Text  # 富文本行，流水各元素的载体
from textual import events  # Resize 事件（欢迎卡随窗口重排）
from textual.containers import VerticalScroll  # 垂直滚动容器（消息流承载）
from textual.widgets import Static  # 静态部件基类（单条消息载体）

from tui.textutils import fold_multiline, truncate_cells  # 折行与显示宽度截断
from tui.theme import GRAY, RED, USER_BAR_BG  # 主题常量
from tui.welcome import build_title, build_welcome  # 欢迎卡标题与内容构建


class WelcomeCard(Static):
    """常驻欢迎卡：铺满宽度、随窗口 resize 自动重排、模型名即时刷新。

    类变量：can_focus=False（焦点恒留输入框）。
    实例：_model 当前模型文案；render 按卡内宽度实时构建内容。
    生命周期：compose 创建；set_model 由 boot 与配置屏保存调用。
    """

    can_focus = False

    def __init__(self) -> None:
        """初始化：空内容挂载，模型文案由 boot 注入。

        Args: None。
        """
        super().__init__("", id="welcome")  # id 绑定部件自身，CSS #welcome 恒生效
        self._model: str = "-"
        self._last_w: int = -1  # 上次重排宽度（resize 守卫）
        self.border_title = build_title()

    def set_model(self, model: str) -> None:
        """更新模型显示文案并触发重排。

        Args: model 模型显示文案。Returns: None。
        """
        self._model = model
        self.refresh(layout=True)

    def on_resize(self, event: events.Resize) -> None:
        """窗口尺寸变化：宽度实际变化时才重排（防高度抖动循环）。"""
        if event.size.width != self._last_w:
            self._last_w = event.size.width
            self.refresh(layout=True)

    def _width(self) -> int:
        """卡内内容宽度；布局未完成时回退终端宽度估算。

        Args: None。Returns: int 显示格数。
        """
        if self.content_size.width:
            return self.content_size.width
        try:
            return max(self.app.size.width - 8, 40)
        except Exception:  # noqa: BLE001 无 app 上下文的兜底（理论不可达）
            return 80

    def render(self):
        """按当前卡内宽度构建内容（每次刷新重算，保证 resize 跟随）。"""
        return build_welcome(self._model, self._width())




class Transcript(VerticalScroll):
    """消息流容器：每条消息独立部件，思考面板可内联挂载。

    类变量：can_focus=False（焦点恒留输入框）。
    实例：写入时若原本贴底则自动跟随滚动；用户上翻查看历史时不打扰。
    生命周期：compose 创建，App 全程复用；clear 由 ctrl+l 调用。
    """

    can_focus = False

    def _w(self) -> int:
        """可用内容宽度；layout 未完成(size=0)时回退 app 终端宽。

        Args: None。Returns: int 显示格数。
        """
        if self.size.width:
            return self.size.width
        try:
            return self.app.size.width
        except Exception:  # noqa: BLE001 无 app 上下文的兜底（理论不可达）
            return 80

    def _pinned(self) -> bool:
        """当前是否贴底（决定写入后是否跟随滚动）。"""
        return self.scroll_y >= self.max_scroll_y - 1

    def _emit(self, content) -> None:
        """追加一条消息部件；原贴底时跟随滚动到末尾。

        Args: content rich 渲染对象。Returns: None。
        """
        pin = self._pinned()
        self.mount(Static(content))
        if pin:
            self.call_after_refresh(self.scroll_end, animate=False)

    def mount_thinking(self, panel) -> None:
        """内联挂载思考面板（跟在最新消息之后）并滚动进视野。

        Args: panel ThinkingPanel 实例。Returns: None。
        """
        self.mount(panel)
        self.call_after_refresh(self.scroll_end, animate=False)

    def texts(self) -> list[str]:
        """全部消息文本快照（rich Text 归一为纯文本；测试与取证用）。"""
        out: list[str] = []
        for child in self.children:
            if isinstance(child, Static):
                value = child.content
                out.append(value.plain if hasattr(value, "plain") else str(value))
        return out

    def clear(self) -> None:
        """清空全部消息部件（ctrl+l 清屏）。"""
        self.remove_children()

    def write_user(self, text: str) -> None:
        """用户命令条：全宽背景条 + 多行折叠摘要 + 尾随空行。

        Args: text 用户原始输入。Returns: None。
        """
        width = max(self._w() - 2, 12)
        folded, _ = fold_multiline(text)
        line = truncate_cells(f"> {folded}", width)
        pad = " " * max(width - _cells(line), 0)
        self._emit(Text(line + pad, style=f"on {USER_BAR_BG} bold white"))
        self._emit(Text(" "))

    def write_assistant(self, text: str) -> None:
        """助手回复：按空行分段，每个文本块一个 ⏺ 前缀（与 Claude Code 语义一致）。

        Args: text 回复文本。Returns: None。
        """
        blocks = [b.strip() for b in re.split(r"\n\s*\n", text.rstrip()) if b.strip()]
        if not blocks:
            return
        self._emit(Text(" "))
        for block in blocks:
            t = Text()
            t.append("⏺ ", style="bold white")
            t.append(block)
            self._emit(t)

    def write_action(self, name: str, args: dict) -> None:
        """工具调用行：└ + 粗体工具名 + 灰色参数（按宽度截断）。

        Args: name 工具名; args 参数字典。Returns: None。
        """
        brief = ", ".join(f"{k}={str(v)[:50]!r}" for k, v in list(args.items())[:4])
        budget = max(self._w() - 4 - _cells(name) - 2, 10)
        brief = truncate_cells(brief, budget)
        t = Text("└ ", style=GRAY)
        t.append(name, style="bold white")
        if brief:
            t.append(f"({brief})", style=GRAY)
        self._emit(t)

    def write_result(self, name: str, result: str) -> None:
        """工具结果行：两格缩进 └，灰字；空结果显 (no content)；错误红字；超两行折叠。

        Args: name 工具名（日志定位用）; result 结果文本。Returns: None。
        """
        lines = result.rstrip().splitlines() if result.strip() else ["(no content)"]
        shown = lines if len(lines) <= 2 else lines[:2] + ["…"]
        limit = max(self._w() - 6, 20)
        style = f"bold {RED}" if result.startswith("ERROR") else GRAY
        t = Text()
        for i, ln in enumerate(shown):
            t.append(("  └ " if i == 0 else "    ") + truncate_cells(ln, limit) + "\n", style=style)
        self._emit(t)

    def write_system(self, text: str) -> None:
        """系统提示：└ 灰字；⚠/❌ 前缀错误转红色 X 行。

        Args: text 提示文本。Returns: None。
        """
        stripped = text.rstrip()
        t = Text()
        if stripped.startswith(("⚠", "❌")):
            t.append("X ", style=f"bold {RED}")
            t.append(stripped.lstrip("⚠❌ ").strip(), style=RED)
        else:
            t.append("└ ", style=GRAY)
            t.append(stripped, style=GRAY)
        self._emit(t)
        self._emit(Text(" "))

    def write_tool_note(self, text: str) -> None:
        """轻量附注行（截图路径等）：两格缩进 └ 灰字。

        Args: text 附注文本。Returns: None。
        """
        self._emit(Text("  └ " + text, style=GRAY))


def _cells(s: str) -> int:
    """字符串显示宽度（CJK 一字两格）。

    Args: s 输入串。Returns: int 显示格数。
    """
    from rich.cells import cell_len  # 局部导入避免模块级第三方耦合

    return cell_len(s)
