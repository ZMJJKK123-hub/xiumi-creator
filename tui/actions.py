"""快捷键动作：从 App 薄壳拆出的键位行为集合。

Rule2 §3：Mixin 单一职责，app.py 只保留组装；宿主需提供
transcript/history/_busy/_worker/_set_busy/open_help/_welcome_model/_welcome_cwd。
"""
from __future__ import annotations

from textual.widgets import Input  # 输入框类型标注


class ShortcutActions:
    """全局快捷键动作集合。

    类职责：实现 App BINDINGS 指向的全部 action_* 方法。
    类变量：无。
    生命周期：随宿主 App 存在；每个方法对应一个键位，见 App.BINDINGS。
    """

    def action_interrupt(self) -> None:
        """esc：取消进行中的任务 worker。"""
        if self._busy and self._worker is not None:
            self._worker.cancel()
            self._set_busy(False)
            self.transcript().write_system("⏹ 已中断（esc）")

    def action_help(self) -> None:
        """?：打开帮助浮层。"""
        self.open_help()

    def action_clear_logs(self) -> None:
        """ctrl+l：清屏并重绘欢迎卡。"""
        t = self.transcript()
        t.clear()
        t.write_welcome(self._welcome_model(), self._welcome_cwd())

    def action_history_prev(self) -> None:
        """↑：回溯上一条历史并回填输入框。"""
        inp = self.query_one("#task", Input)
        inp.value = self.history.prev(inp.value)
        inp.cursor_position = len(inp.value)

    def action_history_next(self) -> None:
        """↓：回溯下一条历史，到底恢复草稿。"""
        inp = self.query_one("#task", Input)
        inp.value = self.history.next()
        inp.cursor_position = len(inp.value)

    def action_scroll_transcript_up(self) -> None:
        """PgUp：流水上翻一页。"""
        try:
            self.transcript().scroll_page_up()
        except Exception as exc:  # noqa: BLE001 翻页失败仅记调试
            self.logger.debug("scroll_up 失败: %s", exc)

    def action_scroll_transcript_down(self) -> None:
        """PgDn：流水下翻一页。"""
        try:
            self.transcript().scroll_page_down()
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("scroll_down 失败: %s", exc)
