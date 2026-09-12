"""欢迎卡构建：双栏仪表卡与窄终端简版的渲染逻辑。

Rule2 §1 表现层构建逻辑独立成模块，widgets.Transcript 只负责写入。
"""
from __future__ import annotations

from rich.align import Align  # 居中对齐包装
from rich.box import Box  # 自定义 box 字符集（双栏分隔线）
from rich.console import Group  # 纵向组合多个渲染片段
from rich.panel import Panel  # 圆角面板容器
from rich.padding import Padding  # 内边距包装
from rich.table import Table  # 双栏栅格
from rich.text import Text  # 富文本行

from tui.textutils import hanging_bullets  # 条目折行
from tui.theme import ACCENT, DIM_ACCENT, GRAY, VERSION  # 主题色与版本号

# 命令速查表：欢迎卡右栏条目（单条控制在一行内，避免折行）
QUICKREF = [
    "/model    配置模型",
    "/file 路径 载入任务",
    "/login    登录",
    "/shot     截图",
    "/help     帮助",
    "esc       中断任务",
    "ctrl+q    退出",
]

# mascot 像素图案预留位：图案定稿后填入字符串列表，以主色渲染
MASCOT_ART: list[str] | None = None

# 宽卡右栏最小内容宽：速查最长行 + 项目符号；终端放不下则退简版卡
_MIN_REF = 26

# 只有列间竖线的 box（无外框无横线），用于双栏暗橙分隔线
_INNER_DIVIDER = Box(
    "    \n" "    \n" "    \n" "    \n" "  │ \n" "    \n" "    \n" "    "
)


def _build_title() -> Text:
    """构建卡片标题：`xiumi-agent v0.1.1`，名称粗体橙 + 版本灰。

    Args: None。Returns: Text 标题片段（嵌入面板上边框）。
    """
    title = Text()
    title.append(" xiumi-agent ", style=f"bold {ACCENT}")
    title.append(VERSION, style=GRAY)
    return title


def _compact_card(model: str) -> Panel:
    """构建窄终端简版卡（双栏放不下时替代，避免溢出与折行）。

    Args: model 模型显示文案。Returns: Panel。
    """
    content = Group(
        Text("Welcome back!", style="bold white", justify="center"),
        Text(),
        Align.center(Text(f"模型: {model}", style=GRAY)),
        Text(),
        Text("· /help 查看帮助", style="white"),
    )
    return Panel(content, title=_build_title(), title_align="left", border_style=ACCENT, padding=(0, 1))


def _ref_width(width: int) -> int:
    """右栏内容宽：双栏比例 38/62 后再让速查区至少保底。

    Args: width 终端宽度。Returns: 右栏内容宽（格）。
    """
    return max(int((width - 8) * 0.62) - 2, _MIN_REF)


def build_welcome(model: str, width: int) -> Panel:
    """构建欢迎卡：宽终端双栏（欢迎/速查），窄终端简版。

    Args: model 模型显示文案; width 可用宽度（格）。
    Returns: rich Panel，由 Transcript 直接 write。
    """
    if width < 8 + _MIN_REF / 0.62 + 20:  # 左栏欢迎语放不下时退简版
        return _compact_card(model)

    left_lines: list = [Align.center(Text("Welcome back!", style="bold white")), Text()]
    if MASCOT_ART:
        left_lines += [Align.center(Text(row, style=ACCENT)) for row in MASCOT_ART]
    else:
        left_lines += [Text() for _ in range(4)]  # 图案预留位
    left_lines.append(Align.center(Text(f"模型: {model}", style=GRAY)))

    right = Group(
        Text("命令与快捷键", style=f"bold {ACCENT}"),
        *hanging_bullets(QUICKREF, _ref_width(width)),
    )

    grid = Table(box=_INNER_DIVIDER, show_header=False, show_edge=False, expand=True, border_style=DIM_ACCENT)
    grid.add_column(ratio=38)
    grid.add_column(ratio=62)
    grid.add_row(Padding(Group(*left_lines), (0, 1)), Padding(right, (0, 1, 0, 0)))
    return Panel(grid, title=_build_title(), title_align="left", border_style=ACCENT, padding=(0, 1))
