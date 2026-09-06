"""终端流水渲染：严格按项目 UI 规格书实现（Claude Code v2.1.158 风格）。

规格要点：
- 配色：背景 #0C0C0C · 主色 #E06C38（橙）· 亮白 #FFFFFF · 灰 #8E8E8E · 错误 #E05252
- 欢迎头部卡片：橙色圆角框、标题嵌入上边框、左(欢迎+mascot+元信息)右(Tips/What's new)双栏、暗橙竖分隔线
- 交互流水：用户命令条（全宽 #2A2A2A 背景条 `> cmd`）；子结果用 L 形树 `└`（灰），嵌套结果再缩进一层
- 错误用 X 前缀红色；空结果显示 (no content)
- mascot 像素图案预留位（MASCOT_ART，定稿后填入即可）
"""
from __future__ import annotations

from rich import box
from rich.align import Align
from rich.box import Box
from rich.cells import cell_len
from rich.console import Group
from rich.panel import Panel
from rich.padding import Padding
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from textual import events
from textual.widgets import Input, RichLog

ACCENT = "#E06C38"        # 主色（暖橙/陶土）
DIM_ACCENT = "#a8542f"    # 暗橙（分隔线）
GRAY = "#8E8E8E"          # 次级文本/边框
RED = "#E05252"           # 错误
USER_BAR_BG = "#2A2A2A"   # 用户命令条背景
VERSION = "v0.1.0"

# mascot 像素图案预留位：等图案定稿后填入（每行一个字符串，可用 █▄ 块字符），自动以主色渲染
MASCOT_ART: list[str] | None = None

CHANGELOG = [
    "· Claude Code 风格界面：欢迎面板 / └ 流水 / spinner",
    "· 后台浏览器工具箱 browser_open/browser_close（background 参数）",
    "· 双模式登录：微信扫码弹图 / 账密代填",
]

TIPS = [
    "· 直接输入任务，例如：写一篇秋天咖啡店探店推文，主色暖棕",
    "· /file 路径 载入 Markdown 任务，支持 [img:路径] 插图标记",
    "· ? 查看快捷键 · esc 中断任务 · ↑↓ 翻阅输入历史",
]

# 只有列间竖线（row.cross=│），无外框无横线的 box —— 欢迎卡双栏之间的暗橙分隔线
INNER_DIVIDER = Box(
    "    \n"  # top
    "    \n"  # head
    "    \n"  # head_row
    "    \n"  # mid
    "  │ \n"  # row: 左空 横空 竖│ 右空
    "    \n"  # foot_row
    "    \n"  # foot
    "    "    # bottom
)


def _truncate_cells(line: str, max_cells: int) -> str:
    """按显示宽度截断（CJK 一字占两格），截后含省略号不超过 max_cells。"""
    if cell_len(line) <= max_cells:
        return line
    out = ""
    for ch in line:
        if cell_len(out + ch) + 1 > max_cells:  # 留 1 格给 …
            break
        out += ch
    return out + "…"


def _hanging_bullets(lines: list[str], width_cells: int = 40) -> list[Text]:
    """把条目按显示宽度折行，首行 `· ` 前缀、续行两格悬挂缩进（避免顶格换行）。

    入参若已带 "· " 前缀会先剥掉，统一由本函数添加，防止出现双重前缀。
    """
    out: list[Text] = []
    for raw_line in lines:
        line = raw_line.lstrip()
        if line.startswith("·"):
            line = line[1:].lstrip()
        elif line.startswith("- "):
            line = line[2:].lstrip()
        first = True
        while line:
            limit = width_cells - 2
            chunk = line
            while cell_len(chunk) > limit:
                chunk = chunk[:-1]
            if chunk != line and " " in chunk:
                cut = chunk.rfind(" ")
                if cut > 2:
                    chunk, rest = chunk[:cut], line[cut + 1 :]
                else:
                    rest = line[len(chunk) :]
            elif chunk != line:
                rest = line[len(chunk) :]
            else:
                rest = ""
            out.append(Text(("· " if first else "  ") + chunk.rstrip(), style="white"))
            line = rest.lstrip()
            first = False
    return out


class TaskInput(Input):
    """任务输入框：输入为空时按 ? 直接打开快捷键帮助（Claude Code 行为），非空时正常输入。

    注意：Textual 按 MRO 分别派发子类与基类的 _on_key，这里对非 ? 按键
    不做任何处理（也不调 super()），交由 Input 基类自身的 _on_key 完成输入。
    """

    def _on_key(self, event: events.Key) -> None:
        if event.key == "question_mark" and not self.value.strip():
            event.stop()
            event.prevent_default()
            self.app.action_help()


class Transcript(RichLog):
    """单栏滚动流水：用户命令条 / 工具执行 / 结果 / 提示按序写入。

    wrap=True + min_width=0：按实际宽度换行、不强制 78 列最小宽，
    配合按显示宽度的截断，彻底避免横向滚动条。
    """

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("wrap", True)
        kwargs.setdefault("min_width", 0)
        super().__init__(*args, **kwargs)

    def _w(self) -> int:
        """可用内容宽度：layout 未完成(size=0)时回退到终端宽度。"""
        if self.size.width:
            return self.size.width
        try:
            return self.app.size.width
        except Exception:
            return 80

    # ---- 欢迎头部卡片 ----
    def write_welcome(self, model: str = "-", cwd: str = "-") -> None:
        title = Text()
        title.append(" xiumi-agent ", style=f"bold {ACCENT}")
        title.append(VERSION, style=GRAY)

        # 窄终端：双栏卡片自然宽度放不下（会撑出横向滚动条），退化为单栏简版
        if self._w() < 62:
            content = Group(
                Text("Welcome back!", style="bold white", justify="center"),
                Text(),
                Align.center(Text(f"{model} · API 按量计费", style=GRAY)),
                Align.center(Text(cwd, style=f"dim {GRAY}", overflow="fold")),
                Text(),
                Text("· 直接输入任务开始", style="white"),
                Text(f"· ? 快捷键 · esc 中断", style="white"),
            )
            self.write(Panel(content, title=title, title_align="left", border_style=ACCENT, padding=(0, 1)))
            self.write("")
            return

        left_lines: list = [Align.center(Text("Welcome back!", style="bold white")), Text()]
        if MASCOT_ART:
            left_lines += [Align.center(Text(row, style=ACCENT)) for row in MASCOT_ART]
        else:
            left_lines += [Text() for _ in range(4)]  # 图案预留位（空行）
        left_lines += [
            Align.center(Text(f"{model} · API 按量计费", style=GRAY)),
            Align.center(Text(cwd, style=f"dim {GRAY}", overflow="fold")),  # 折行显示完整路径
        ]
        left = Group(*left_lines)

        # 右栏实际内容宽（卡片总宽 - 边框/内边距/左栏 45%），据此折行避免错乱
        tips_width = max(int((self._w() - 8) * 0.55) - 2, 24)
        right = Group(
            Text("Tips for getting started", style=f"bold {ACCENT}"),
            *_hanging_bullets(TIPS, tips_width),
            Rule(style=GRAY),
            Text("What's new", style=f"bold {ACCENT}"),
            *_hanging_bullets(CHANGELOG, tips_width),
            Text("详见 README.md", style=f"italic {GRAY}"),
        )

        grid = Table(box=INNER_DIVIDER, show_header=False, show_edge=False, expand=True, border_style=DIM_ACCENT)
        grid.add_column(ratio=45)
        grid.add_column(ratio=55)
        grid.add_row(Padding(left, (0, 1)), Padding(right, (0, 1, 0, 0)))

        self.write(Panel(grid, title=title, title_align="left", border_style=ACCENT, padding=(0, 1)))
        self.write("")

    # ---- 交互流水 ----
    def write_user(self, text: str) -> None:
        """用户命令条：全宽 #2A2A2A 背景条 `> cmd`；多行折叠为首行 + 行数标记。"""
        width = max(self._w() - 2, 12)
        lines = [ln for ln in text.rstrip().splitlines() if ln.strip()]
        if len(lines) > 1:
            line = f"> {lines[0].strip()}  ⏎ …({len(lines)} 行)"
        else:
            line = "> " + (lines[0].strip() if lines else "")
        line = _truncate_cells(line, width)  # 按显示宽度截断，避免 CJK 溢出
        pad = " " * max(width - cell_len(line), 0)
        self.write(Text(line + pad, style=f"on {USER_BAR_BG} bold white"))

    def write_assistant(self, text: str) -> None:
        t = Text()
        t.append("⏺ ", style="bold white")
        t.append(text.rstrip() + "\n")
        self.write(t)
        self.write("")

    def write_action(self, name: str, args: dict) -> None:
        brief = ", ".join(f"{k}={str(v)[:50]!r}" for k, v in list(args.items())[:4])
        # 参数按显示宽度截断，保证整行不溢出
        budget = max(self._w() - 4 - cell_len(name) - 2, 10)
        brief = _truncate_cells(brief, budget)
        t = Text("└ ", style=GRAY)
        t.append(name, style="bold white")
        if brief:
            t.append(f"({brief})", style=GRAY)
        self.write(t)

    def write_result(self, name: str, result: str) -> None:
        if not result.strip():
            lines = ["(no content)"]
        else:
            lines = result.rstrip().splitlines()
        shown = lines if len(lines) <= 2 else lines[:2] + ["…"]
        limit = max(self._w() - 6, 20)
        style = f"bold {RED}" if result.startswith("ERROR") else GRAY
        t = Text()
        for i, ln in enumerate(shown):
            t.append(("  └ " if i == 0 else "    ") + _truncate_cells(ln, limit) + "\n", style=style)
        self.write(t)

    def write_system(self, text: str) -> None:
        stripped = text.rstrip()
        is_err = stripped.startswith(("⚠", "❌", "X "))
        t = Text()
        if is_err:
            t.append("X ", style=f"bold {RED}")
            t.append(stripped.lstrip("⚠❌X ").strip() + "\n", style=RED)
        else:
            t.append("└ ", style=GRAY)
            t.append(stripped + "\n", style=GRAY)
        self.write(t)  # 真正写入内容（此前误写成空串导致系统行全部丢失）
        self.write("")

    def write_tool_note(self, text: str) -> None:
        self.write(Text("  └ " + text, style=GRAY))
