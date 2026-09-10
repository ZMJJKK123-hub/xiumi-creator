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

# 命令速查表：欢迎卡右栏条目
QUICKREF = [
    "/model    配置模型、Key、地址",
    "/file 路径 载入任务",
    "/login    登录",
    "/shot     截图",
    "/help     帮助",
    "esc       中断任务",
    "ctrl+q    退出",
]

# mascot 像素图案预留位：图案定稿后填入字符串列表，以主色渲染
MASCOT_ART: list[str] | None = None

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


def _compact_card(model: str, cwd: str, width: int) -> Panel:
    """构建窄终端简版卡（<62 列时替代双栏卡避免溢出）。

    Args: model 模型显示文案; cwd 工作目录; width 终端宽度。Returns: Panel。
    """
    content = Group(
        Text("Welcome back!", style="bold white", justify="center"),
        Text(),
        Align.center(Text(f"模型: {model}", style=GRAY)),
        Align.center(Text(cwd, style=f"dim {GRAY}", overflow="fold")),
        Text(),
        Text("· /help 查看帮助", style="white"),
    )
    return Panel(content, title=_build_title(), title_align="left", border_style=ACCENT, padding=(0, 1))


def build_welcome(model: str, cwd: str, width: int) -> Panel:
    """构建欢迎卡：宽终端双栏（欢迎/速查），窄终端简版。

    Args: model 模型显示文案; cwd 工作目录显示; width 可用宽度（格）。
    Returns: rich Panel，由 Transcript 直接 write。
    """
    if width < 62:
        return _compact_card(model, cwd, width)

    left_lines: list = [Align.center(Text("Welcome back!", style="bold white")), Text()]
    if MASCOT_ART:
        left_lines += [Align.center(Text(row, style=ACCENT)) for row in MASCOT_ART]
    else:
        left_lines += [Text() for _ in range(4)]  # 图案预留位
    left_lines += [
        Align.center(Text(f"模型: {model}", style=GRAY)),
        Align.center(Text(cwd, style=f"dim {GRAY}", overflow="fold")),
    ]

    ref_width = max(int((width - 8) * 0.55) - 2, 24)  # 右栏内容宽，据此折行
    right = Group(
        Text("命令与快捷键", style=f"bold {ACCENT}"),
        *hanging_bullets(QUICKREF, ref_width),
    )

    grid = Table(box=_INNER_DIVIDER, show_header=False, show_edge=False, expand=True, border_style=DIM_ACCENT)
    grid.add_column(ratio=45)
    grid.add_column(ratio=55)
    grid.add_row(Padding(Group(*left_lines), (0, 1)), Padding(right, (0, 1, 0, 0)))
    return Panel(grid, title=_build_title(), title_align="left", border_style=ACCENT, padding=(0, 1))
