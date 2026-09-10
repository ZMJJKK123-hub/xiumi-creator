"""xiumi-agent 入口。

用法（安装全局命令后任意目录可用，等价于 python main.py）:
  xiumi            启动 TUI
  xiumi recon      对秀米登录页/编辑器做 DOM 踩点（生成 recon/ 报告，更新选择器用）
  xiumi version    显示版本
"""
from __future__ import annotations

import sys  # 命令行参数与终端重置
from pathlib import Path  # 探针写日志  # 命令行参数与退出终端重置


def _reset_terminal() -> None:
    """恢复终端模式（鼠标追踪/光标）。

    TUI 会话异常退出可能遗留鼠标上报模式，导致鼠标移动刷出 [N;x;yM 转义码；
    启动与退出各调用一次，双保险。Windows 下先强制打开 VT 输出，确保重置码被解析。
    """
    codes = "\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1015l\x1b[?25h\x1b[0m"
    try:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        sys.stdout.write(codes)
        sys.stdout.flush()
    except Exception:
        pass


def main() -> None:
    _reset_terminal()  # 清理上次会话可能遗留的鼠标模式，避免一启动就刷转义码
    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    if arg in ("recon",):
        import asyncio

        from scripts.recon import run_recon

        asyncio.run(run_recon())
        return

    if arg in ("version", "--version", "-V"):
        from tui.widgets import VERSION

        print(f"xiumi-agent {VERSION}")
        return

    if arg in ("--help", "-h", "help"):
        print(__doc__)
        return

    from tui.app import XiumiAgentApp

    try:
        # faulthandler：原生层崩溃（段错误等无 stderr 的静默死亡）时留全套栈转储
        import faulthandler

        from core.config import XIUMI_HOME

        dump = XIUMI_HOME / "logs" / "faulthandler.log"
        dump.parent.mkdir(parents=True, exist_ok=True)
        faulthandler.enable(open(dump, "w", encoding="utf-8"), all_threads=True)
        # mouse 保持默认启用：用户需要鼠标点击与滚轮；异常退出遗留的鼠标上报
        # 模式由 _reset_terminal 兜底复位
        XiumiAgentApp().run()
        # 诊断探针：正常退出也留痕（区分自然退出/被外部终止/崩溃）
        Path(XIUMI_HOME / "logs" / "exit_trace.txt").write_text(
            f"TUI run() 正常返回 at {__import__('time').strftime('%H:%M:%S')}", encoding="utf-8"
        )
    except KeyboardInterrupt:
        pass
    finally:
        _reset_terminal()


if __name__ == "__main__":
    main()
