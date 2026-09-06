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

    XiumiAgentApp().run()


if __name__ == "__main__":
    main()
