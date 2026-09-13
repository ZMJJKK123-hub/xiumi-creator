"""纯文本排版算法：显示宽度世界的工具箱。

架构定位：tui 表现层的共享算法库；上游 widgets（命令条截断/结果折叠）
与 welcome（速查悬挂缩进）。只认 rich 的"显示格"概念（CJK=2 格），
不含任何框架依赖——复制到任何项目可直接用。
"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

from rich.cells import cell_len  # 计算字符串显示宽度（CJK 一字两格）
from rich.text import Text  # 富文本对象，输出带样式行


def truncate_cells(line: str, max_cells: int) -> str:
    """按显示宽度截断，截断后含省略号且不超过 max_cells。

    Globals Used: None。Calls: rich.cell_len。
    Args: line 原始行; max_cells 目标显示宽度上限。
    Returns: 截断后的字符串，超宽时以 … 结尾。
    """
    if cell_len(line) <= max_cells:
        return line
    out = ""
    for ch in line:
        if cell_len(out + ch) + 1 > max_cells:  # 预留 1 格给省略号
            break
        out += ch
    return out + "…"


def fold_multiline(text: str) -> tuple[str, int]:
    """把多行任务文本折叠为单行摘要。

    Globals Used: None。Calls: 无。
    Args: text 原始多行文本。Returns: (摘要行, 非空行数)。
    多行时摘要为首行 + 行数标记，如 `# 示例  ⏎ …(16 行)`。
    """
    lines = [ln for ln in text.rstrip().splitlines() if ln.strip()]
    if len(lines) > 1:
        return f"{lines[0].strip()}  ⏎ …({len(lines)} 行)", len(lines)
    return (lines[0].strip() if lines else ""), max(len(lines), 1)


def hanging_bullets(items: list[str], width_cells: int = 40) -> list[Text]:
    """把条目列表按显示宽度折行，首行加 · 前缀、续行两格缩进。

    Globals Used: None。Calls: truncate_cells。
    Args: items 原始条目（可带或省略 · 前缀）; width_cells 目标显示宽度。
    Returns: 每条目若干 Text 行的列表，白色样式。
    """
    out: list[Text] = []
    for raw_line in items:
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
                    chunk, line = chunk[:cut], line[cut + 1 :]
                else:
                    line = line[len(chunk) :]
            elif chunk != line:
                line = line[len(chunk) :]
            else:
                line = ""
            out.append(Text(("· " if first else "  ") + chunk.rstrip(), style="white"))
            line = line.lstrip()
            first = False
    return out
