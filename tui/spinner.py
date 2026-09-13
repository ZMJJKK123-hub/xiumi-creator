"""任务进行中的 spinner：六帧符号 + 固定 thinking 字样 + 秒数。

数据与渲染分离：帧序列取自 Claude Code 实际行为（调研确认）；
动词固定为 thinking（用户指定，不再随机轮换）。
"""
from __future__ import annotations

import time  # 计算任务已耗时秒数

from rich.text import Text  # 富文本行，用于着色拼接

from tui.theme import ACCENT, GRAY  # 主题色：符号橙、计时灰

# 六帧旋转符号（调研自 Claude Code 真实动画）
FRAMES = ["·", "✢", "✳", "✶", "✻", "✽"]

# 固定动词：思考中
VERB = "thinking"

# 忙碌提示行文案
BUSY_TIP = "└ Tip: esc 中断当前任务，已完成的步骤不会回滚"


class SpinnerState:
    """spinner 帧状态机。

    职责：维护当前帧索引，按 tick 推进并渲染富文本行。
    属性：frame_idx 当前帧下标。
    生命周期：App 构造创建，每 0.12s tick 一次，任务结束停用。
    """

    def __init__(self) -> None:
        self.frame_idx: int = 0

    def tick(self) -> None:
        """推进一帧。

        Args: None。Returns: None。Globals Used: None（FRAMES 为模块常量）。
        """
        self.frame_idx = (self.frame_idx + 1) % len(FRAMES)

    def render(self, started_at: float) -> Text:
        """渲染当前 spinner 双行文本。

        Args: started_at 任务开始时间戳（time.time）。Returns: 两行 Text，
        第一行 `✶ thinking... (12s)`，第二行 esc 中断提示。
        """
        elapsed = max(int(time.time() - started_at), 0)
        line = Text(FRAMES[self.frame_idx] + " ", style=f"bold {ACCENT}")
        line.append(f"{VERB}... ", style="white")
        line.append(f"({elapsed}s)", style=GRAY)
        line.append("\n")
        line.append(BUSY_TIP, style=f"dim {GRAY}")
        return line
