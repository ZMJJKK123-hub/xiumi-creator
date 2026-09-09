"""任务进行中的 spinner：六帧符号 + 随机动名词 + 秒数。

数据与渲染分离：帧序列/词表取自 Claude Code 实际行为（调研确认）。
"""
from __future__ import annotations

import time  # 计算任务已耗时秒数

from rich.text import Text  # 富文本行，用于着色拼接

from tui.theme import ACCENT, GRAY  # 主题色：符号橙、计时灰

# 六帧旋转符号（调研自 Claude Code 真实动画）
FRAMES = ["·", "✢", "✳", "✶", "✻", "✽"]

# 随机动名词表（节选自 Claude Code 的 184 词表）
VERBS = [
    "Pondering", "Mulling", "Simmering", "Marinating", "Noodling", "Vibing",
    "Rethinking", "Synthesizing", "Musing", "Stewing", "Spinning", "Wandering",
    "Brewing", "Whisking", "Seasoning", "Proofing", "Mustering", "Meandering",
    "Baking", "Percolating",
]

# 忙碌提示行文案
BUSY_TIP = "└ Tip: esc 中断当前任务，已完成的步骤不会回滚"


class SpinnerState:
    """spinner 帧状态机。

    职责：维护当前帧/动词索引，按 tick 推进并渲染富文本行。
    属性：frame_idx 当前帧下标；verb_idx 当前动词下标。
    生命周期：App 构造创建，每 0.12s tick 一次，任务结束停用。
    """

    def __init__(self) -> None:
        self.frame_idx: int = 0
        self.verb_idx: int = 0

    def tick(self) -> None:
        """推进一帧；整轮（6 帧）结束时切换到下一个动词。

        Args: None。Returns: None。Globals Used: None（FRAMES/VERBS 为模块常量）。
        """
        self.frame_idx = (self.frame_idx + 1) % len(FRAMES)
        if self.frame_idx == 0:
            self.verb_idx = (self.verb_idx + 1) % len(VERBS)

    def render(self, started_at: float) -> Text:
        """渲染当前 spinner 双行文本。

        Args: started_at 任务开始时间戳（time.time）。Returns: 两行 Text，
        第一行 `✶ Pondering... (12s)`，第二行 esc 中断提示。
        """
        elapsed = max(int(time.time() - started_at), 0)
        line = Text(FRAMES[self.frame_idx] + " ", style=f"bold {ACCENT}")
        line.append(f"{VERBS[self.verb_idx]}... ", style="white")
        line.append(f"({elapsed}s)", style=GRAY)
        line.append("\n")
        line.append(BUSY_TIP, style=f"dim {GRAY}")
        return line
