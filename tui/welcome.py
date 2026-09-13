"""欢迎卡内容构建：双栏内容与窄终端简版。

Rule2 §1 表现层构建逻辑独立成模块；边框由 widgets.WelcomeCard 的 CSS 提供，
此处只产出卡内内容，宽度由部件传入，resize 时部件重算。
"""
from __future__ import annotations

from rich.align import Align  # 居中对齐包装
from rich.box import Box  # 自定义 box 字符集（双栏分隔线）
from rich.console import Group  # 纵向组合多个渲染片段
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
    "ctrl+o    思考展开",
    "ctrl+q    退出",
]

# mascot 像素图案预留位：图案定稿后填入字符串列表，以主色渲染
MASCOT_ART: list[str] | None = None

# 宽卡右栏最小内容宽：速查最长行 + 项目符号
_MIN_REF = 26

# 内容宽度低于此值退简版：双栏下左栏放不下完整模型行
_COMPACT_MIN = 64

# 只有列间竖线的 box（无外框无横线），用于双栏暗橙分隔线
_INNER_DIVIDER = Box(
    "    \n" "    \n" "    \n" "    \n" "  │ \n" "    \n" "    \n" "    "
)


def build_title() -> str:
    """卡片边框标题：纯文本，颜色由 CSS border-title-color 统一渲染。

    Args: None。Returns: str 标题文本（赋给 WelcomeCard.border_title）。
    """
    return f" xiumi-agent {VERSION}"


def _model_line(model: str) -> Text:
    """模型行：fold 折行而非省略号，任何宽度不出现截断。

    Args: model 模型显示文案。Returns: Text。
    """
    return Text(f"模型: {model}", style=GRAY, overflow="fold")


def _compact(model: str) -> Group:
    """构建窄终端简版内容（双栏放不下时替代，避免溢出与折行）。

    Args: model 模型显示文案。Returns: Group 简版内容。
    """
    return Group(
        Text("Welcome back!", style="bold white", justify="center"),
        Text(),
        Align.center(_model_line(model)),
        Text(),
        Text("· /help 查看帮助", style="white"),
    )


def _ref_width(width: int) -> int:
    """右栏内容宽：双栏比例 45/55 后再让速查区至少保底。

    Args: width 卡内内容宽度。Returns: 右栏内容宽（格）。
    """
    return max(int((width - 8) * 0.55) - 2, _MIN_REF)


def build_welcome(model: str, width: int):
    """构建卡内内容：宽终端双栏（欢迎/速查），窄终端简版。

    Args: model 模型显示文案; width 卡内可用宽度（格）。
    Returns: rich renderable，由 WelcomeCard 直接承载。
    """
    if width < _COMPACT_MIN:
        return _compact(model)

    left_lines: list = [Align.center(Text("Welcome back!", style="bold white")), Text()]
    if MASCOT_ART:
        left_lines += [Align.center(Text(row, style=ACCENT)) for row in MASCOT_ART]
    else:
        left_lines += [Text() for _ in range(2)]  # 图案预留位
    left_lines.append(Align.center(_model_line(model)))

    right = Group(
        Text("命令与快捷键", style=f"bold {ACCENT}"),
        *hanging_bullets(QUICKREF, _ref_width(width)),
    )

    grid = Table(box=_INNER_DIVIDER, show_header=False, show_edge=False, expand=True, border_style=DIM_ACCENT)
    grid.add_column(ratio=45)
    grid.add_column(ratio=55)
    grid.add_row(Padding(Group(*left_lines), (0, 1)), Padding(right, (0, 1, 0, 0)))
    return grid
