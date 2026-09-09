"""xiumi-agent 入口。

用法（安装全局命令后任意目录可用，等价于 python main.py）:
  xiumi            启动 TUI
  xiumi recon      对秀米登录页/编辑器做 DOM 踩点（生成 recon/ 报告，更新选择器用）
  xiumi version    显示版本
"""
from __future__ import annotations

import sys


def main() -> None:
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
        XiumiAgentApp().run()
    except KeyboardInterrupt:
        pass
    finally:
        # 兜底恢复终端：TUI 异常退出时鼠标追踪等模式可能未复位，
        # 会导致鼠标移动刷出 [N;x;yM 转义码；此处统一关闭
        try:
            sys.stdout.write("\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1015l\x1b[?25h\x1b[0m")
            sys.stdout.flush()
        except Exception:
            pass


if __name__ == "__main__":
    main()
