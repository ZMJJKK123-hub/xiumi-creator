"""终端组件：表现层的"积木"——欢迎卡与消息流两个核心部件。

架构定位：tui 表现层；上游 app.compose 装配、events 订阅方写入；
Transcript 是全项目会话内容的唯一呈现容器（部件化：每条消息一个 Static，
思考面板 thinking.ThinkingPanel 经 mount_thinking 内联挂载到发言之后）。
配色在 theme、纯算法在 textutils、卡片内容在 welcome——本文件只有组件本体。

"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

import re  # 助手回复按空行分段

from rich.text import Text  # 富文本行，流水各元素的载体
from textual import events  # Resize 事件（欢迎卡随窗口重排）
from textual.containers import VerticalScroll  # 垂直滚动容器（消息流承载）
from textual.widgets import Static  # 静态部件基类（单条消息载体）

from tui.textutils import fold_multiline, truncate_cells  # 折行与显示宽度截断
from tui.theme import GRAY, RED  # 主题常量
from tui.welcome import build_title, build_welcome  # 欢迎卡标题与内容构建


class WelcomeCard(Static):
    """常驻欢迎卡：铺满宽度、随窗口 resize 自动重排、模型名即时刷新。

    类职责：承载欢迎信息与命令速查，宽度变化时实时重建。
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

        Globals Used: None。Calls: refresh(layout)。
        Args: model 模型显示文案。Returns: None。
        """
        self._model = model
        self.refresh(layout=True)

    def on_resize(self, event: events.Resize) -> None:
        """窗口尺寸变化：宽度实际变化时才重排（防高度抖动循环）。Calls: refresh。Args: event 尺寸事件。Returns: None。"""
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
        """按当前卡内宽度构建内容（每次刷新重算，保证 resize 跟随）。

        Globals Used: None。Calls: build_welcome / _width。Args: None。Returns: rich 渲染对象。
        """
        return build_welcome(self._model, self._width())




class Transcript(VerticalScroll):
    """消息流容器：每条消息独立部件，思考面板可内联挂载。

    类职责：按序呈现全部会话内容，贴底自动跟随滚动。
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
        """当前是否贴底（决定写入后是否跟随滚动）。Args: None。Returns: bool。"""
        return self.scroll_y >= self.max_scroll_y - 1

    def _emit(self, content, cls: str | None = None) -> None:
        """追加一条消息部件；原贴底时跟随滚动到末尾。

        Args: content rich 渲染对象; cls 附加样式类（如用户条边框）。Returns: None。
        """
        pin = self._pinned()
        self.mount(Static(content, classes=cls) if cls else Static(content))
        if pin:
            self.call_after_refresh(self.scroll_end, animate=False)

    def mount_thinking(self, panel) -> None:
        """内联挂载思考面板（跟在最新消息之后）并滚动进视野。

        Globals Used: None。Calls: mount / scroll_end。

        Args: panel ThinkingPanel 实例。Returns: None。
        """
        self.mount(panel)
        self.call_after_refresh(self.scroll_end, animate=False)

    def texts(self) -> list[str]:
        """全部消息文本快照（rich Text 归一为纯文本；测试与取证用）。

        Globals Used: None。Calls: 无（遍历子部件）。Args: None。Returns: str 列表。
        """
        out: list[str] = []
        for child in self.children:
            if isinstance(child, Static):
                value = child.content
                out.append(value.plain if hasattr(value, "plain") else str(value))
        return out

    def clear(self) -> None:
        """清空全部消息部件（ctrl+l 清屏）。Calls: remove_children。Args: None。Returns: None。"""
        self.remove_children()

    def write_user(self, text: str) -> None:
        """用户命令条：白色圆角边框 + 透明底（无填充，杜绝终端渲染差异）+ 尾随空行。

        Globals Used: None。Calls: fold_multiline / truncate_cells / _emit。

        Args: text 用户原始输入。Returns: None。
        """
        folded, _ = fold_multiline(text)
        line = truncate_cells(f"> {folded}", max(self._w() - 6, 12))
        self._emit(Text(line, style="bold white"), cls="msg-user")
        self._emit(Text(" "))

    def write_assistant(self, text: str) -> None:
        """助手回复：按空行分段，每个文本块一个 ⏺ 前缀（与 Claude Code 语义一致）。

        Globals Used: None。Calls: re.split / _emit。

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

        Globals Used: None。Calls: truncate_cells / _emit。

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

        Globals Used: None。Calls: _emit。
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

        Globals Used: None。Calls: _emit。Args: text 附注文本。Returns: None。
        """
        self._emit(Text("  └ " + text, style=GRAY))


def _cells(s: str) -> int:
    """字符串显示宽度（CJK 一字两格）。

    Args: s 输入串。Returns: int 显示格数。
    """
    from rich.cells import cell_len  # 局部导入避免模块级第三方耦合

    return cell_len(s)
