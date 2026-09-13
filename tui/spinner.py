"""任务进行中的 spinner：忙碌态的持续反馈。

架构定位：tui 表现层；状态机由 app._tick_spinner 每 0.12s 驱动（仅忙碌时），
渲染写入 #spinner 部件。与 thinking.ThinkingPanel 的分工：本模块是
"任务进行中"的整体反馈（帧动画+总耗时），思考面板是"模型在想什么"的内容呈现。

动词固定为 thinking（用户指定，不再随机轮换）。
"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

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

    类职责：维护当前帧索引，按 tick 推进并渲染富文本行。
    属性：frame_idx 当前帧下标。
    生命周期：App 构造创建，每 0.12s tick 一次，任务结束停用。
    """

    def __init__(self) -> None:
        self.frame_idx: int = 0

    def tick(self) -> None:
        """推进一帧。Globals Used: FRAMES。Calls: 无。Args: None。Returns: None。"""
        self.frame_idx = (self.frame_idx + 1) % len(FRAMES)

    def render(self, started_at: float) -> Text:
        """渲染当前 spinner 双行文本。Globals Used: FRAMES/VERB/BUSY_TIP。Calls: 无。

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
