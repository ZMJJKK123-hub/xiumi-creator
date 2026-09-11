"""TUI 无头冒烟测试：启动链路 + /login 弹官网转圈等待流程。"""
import asyncio
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from textual.widgets import Input  # 通用输入框

from tui.app import XiumiAgentApp
from tui.widgets import Transcript


async def type_input(app: XiumiAgentApp, pilot, text: str) -> None:
    """聚焦主输入框并逐字输入。Args: app; pilot; text。Returns: None。"""
    await pilot.click("#task")
    inp = app.query_one("#task", Input)
    inp.value = ""
    for ch in text:
        await pilot.press(ch)


async def main() -> None:
    app = XiumiAgentApp()
    async with app.run_test(size=(110, 30)) as pilot:
        # 等启动链路（含登录检查）
        for _ in range(90):
            await pilot.pause(0.5)
            if app.actions or app._boot_failed:
                break
        print("actions:", len(app.actions), "| tools:", len(app.registry.names()))
        for _ in range(90):
            await pilot.pause(0.5)
            if app.ctx and app.ctx.state.get("xiumi_logged_in") is not None or app._boot_failed:
                break
        print("登录判定:", app.ctx.state.get("xiumi_logged_in"))

        # 未登录：不弹任何窗，主屏 + 两命令提示
        assert type(app.screen).__name__ == "Screen"
        _t = app.query_one("#transcript", Transcript)

        # /login：先转圈（即时反馈）→ 弹官网 → esc 可取消
        await type_input(app, pilot, "/login")
        await pilot.press("enter")
        await pilot.pause(1.0)
        print("/login 后 busy:", app._busy, "（应 True 转圈中）")
        assert app._busy
        await pilot.press("escape")
        await pilot.pause(0.6)
        print("esc 取消后 busy:", app._busy, "（应 False）")
        assert not app._busy

        # 状态栏与提示行
        svg = app.export_screenshot()
        texts = [html.unescape(x).replace("\xa0", " ") for x in re.findall(r">([^<>]+)</text>", svg)]
        print("两命令提示行:", any("/login" in x and "/model" in x for x in texts))
        print("取消提示(已中断):", any("已中断" in x for x in texts))
        print("TUI_SMOKE_OK")


if __name__ == "__main__":
    asyncio.run(main())
