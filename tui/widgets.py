"""终端组件：任务输入框与对话流水渲染器。

Rule2 §1 表现层组件；颜色常量在 theme，纯算法在 textutils，
欢迎卡构建在 welcome——本文件只保留组件本身。
"""
from __future__ import annotations

from rich.text import Text  # 富文本行，流水各元素的载体
from textual.widgets import RichLog  # 滚动日志基类（输入框已移至通用 Input）

from tui.textutils import fold_multiline, truncate_cells  # 折行与显示宽度截断
from tui.theme import GRAY, RED, USER_BAR_BG  # 主题常量
from tui.welcome import build_welcome  # 欢迎卡构建（双栏/简版）



class Transcript(RichLog):
    """单栏滚动流水：命令条、工具调用、结果、提示按序写入。

    类变量：can_focus=False（焦点恒留输入框）。
    实例：wrap=True + min_width=0 按实际宽度换行，杜绝横向滚动条。
    生命周期：compose 创建，App 全程复用；_w() 在 layout 未完成时回退终端宽。
    """

    can_focus = False

    def __init__(self, *args, **kwargs) -> None:
        """初始化：注入换行与最小宽度策略。

        Args: *args/**kwargs 透传 RichLog（id 等）。
        """
        kwargs.setdefault("wrap", True)
        kwargs.setdefault("min_width", 0)
        super().__init__(*args, **kwargs)

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

    def write_welcome(self, model: str = "-") -> None:
        """写入欢迎卡：宽终端双栏，窄终端简版。

        Args: model 模型显示文案。Returns: None。
        """
        self.write(build_welcome(model, self._w()))
        self.write("")

    def write_user(self, text: str) -> None:
        """用户命令条：全宽背景条 + 多行折叠摘要。

        Args: text 用户原始输入。Returns: None。
        """
        width = max(self._w() - 2, 12)
        folded, _ = fold_multiline(text)
        line = truncate_cells(f"> {folded}", width)
        pad = " " * max(width - _cells(line), 0)
        self.write(Text(line + pad, style=f"on {USER_BAR_BG} bold white"))

    def write_assistant(self, text: str) -> None:
        """助手回复：⏺ 粗体前缀 + 正文。

        Args: text 回复文本。Returns: None。
        """
        t = Text()
        t.append("⏺ ", style="bold white")
        t.append(text.rstrip() + "\n")
        self.write(t)
        self.write("")

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
        self.write(t)

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
        self.write(t)

    def write_system(self, text: str) -> None:
        """系统提示：└ 灰字；⚠/❌ 前缀错误转红色 X 行。

        Args: text 提示文本。Returns: None。
        """
        stripped = text.rstrip()
        t = Text()
        if stripped.startswith(("⚠", "❌")):
            t.append("X ", style=f"bold {RED}")
            t.append(stripped.lstrip("⚠❌ ").strip() + "\n", style=RED)
        else:
            t.append("└ ", style=GRAY)
            t.append(stripped + "\n", style=GRAY)
        self.write(t)
        self.write("")

    def write_tool_note(self, text: str) -> None:
        """轻量附注行（截图路径等）：两格缩进 └ 灰字。

        Args: text 附注文本。Returns: None。
        """
        self.write(Text("  └ " + text, style=GRAY))


def _cells(s: str) -> int:
    """字符串显示宽度（CJK 一字两格）。

    Args: s 输入串。Returns: int 显示格数。
    """
    from rich.cells import cell_len  # 局部导入避免模块级第三方耦合

    return cell_len(s)
