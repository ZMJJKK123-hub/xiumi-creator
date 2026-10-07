"""按键/粘贴探针 v2：实时落盘，诊断终端把 Ctrl+V / Shift+Insert 送成了什么。

用法:
  cd D:\\xiumi-creator
  python scripts/key_probe.py

步骤:
  1. 先在浏览器/记事本复制一段文本（Ctrl+C）
  2. 探针界面底部输入框按 Ctrl+V，观察新增的日志行
  3. 再按 Shift+Insert，观察新增的日志行
  4. ctrl+q 退出（直接关窗口也行——日志是实时写盘的）

日志文件: logs/key_probe.txt（每条事件实时追加，随时可查看）

判读:
  - 「ACTION paste: ... 插入结果 'xxx'」→ ctrl+v 键到达且读到了剪贴板（应已插入）
  - 「PASTE event: N 字符」→ 终端把按键翻译成了括号粘贴（应已插入）
  - 按下后无任何新行 → 终端把按键整个拦截/丢弃，问题在终端层
  - 「KEY 其他名字」→ 终端送来了异形编码，把名字发给我
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from textual import events
from textual.app import App, ComposeResult
from textual.widgets import RichLog

from tui.widgets import PasteInput

# 探针日志文件：项目根/logs（实时追加）
_OUT = Path(__file__).resolve().parent.parent / "logs" / "key_probe.txt"


def _stamp() -> str:
    """当前时刻的 HH:MM:SS。"""
    return time.strftime("%H:%M:%S")


class ProbeInput(PasteInput):
    """探针输入框：粘贴两条路径的结果实时上报宿主。"""

    def action_paste(self) -> None:
        """记录系统剪贴板读取量与插入预览后执行原生粘贴。"""
        app = self.app
        before = self.value
        super().action_paste()
        inserted = self.value[len(before):]
        preview = (inserted[:30] or "(无插入)") if inserted != before else "(值未变化)"
        if isinstance(app, ProbeApp):
            app.log_line("ACTION", f"paste: 系统剪贴板已读，插入结果 {preview!r}")

    def _on_paste(self, event: events.Paste) -> None:
        """括号粘贴上屏（插入由 Input._on_paste 经 MRO 分发完成，勿 super 调用）。"""
        app = self.app
        if isinstance(app, ProbeApp):
            preview = event.text[:30].replace("\n", "\\n")
            app.log_line("PASTE", f"event.text {len(event.text)} 字符: {preview!r}")


class ProbeApp(App):
    """按键探针：Key/Paste 事件全量上屏 + 实时落盘。"""

    TITLE = "key probe - ctrl+q 退出"

    def compose(self) -> ComposeResult:
        yield RichLog(id="log", markup=False)
        yield ProbeInput(placeholder="先复制文本，再在这里按 Ctrl+V / Shift+Insert", id="probe-input")

    def on_mount(self) -> None:
        self.log_line("INFO", f"driver = {type(self._driver).__name__}")
        self.log_line("INFO", f"textual = {__import__('textual').__version__}  python = {sys.version.split()[0]}")
        # 终端宿主探测：WT_SESSION=Windows Terminal；TERM_PROGRAM=vscode 等常见值
        for var in ("WT_SESSION", "WT_PROFILE_ID", "TERM_PROGRAM", "TERM", "ConEmuANSI", "VSCODE_INJECTION", "PSModulePath"):
            val = os.environ.get(var)
            if val:
                self.log_line("ENV", f"{var} = {val[:60]}")
        self.log_line("INFO", "现在去别处复制一段文本，回来在底部输入框按 Ctrl+V")
        self.query_one("#probe-input", ProbeInput).focus()

    def log_line(self, tag: str, message: str) -> None:
        """一行日志：上屏并实时追加到文件。"""
        line = f"{_stamp()} [{tag}] {message}"
        self.query_one("#log", RichLog).write(line)
        try:
            _OUT.parent.mkdir(parents=True, exist_ok=True)
            with _OUT.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass  # 落盘失败不影响界面诊断

    def on_key(self, event: events.Key) -> None:
        """每个到达应用的按键都上屏（含异形编码）。"""
        if event.key != "ctrl+q":
            self.log_line("KEY", f"key={event.key!r} character={event.character!r}")


if __name__ == "__main__":
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    with _OUT.open("w", encoding="utf-8") as fh:
        fh.write(f"{_stamp()} [INFO] probe 启动（本文件实时追加）\n")
    ProbeApp().run()
