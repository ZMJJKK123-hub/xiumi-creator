"""TUI 无头冒烟测试：启动链路 + 命令式登录流程（/login → 账密屏 → 假凭据真实提交）。"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tui.app import XiumiAgentApp
from tui.widgets import TaskInput, Transcript


async def type_input(app: XiumiAgentApp, pilot, text: str) -> None:
    await pilot.click("#task")
    inp = app.query_one("#task", TaskInput)
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
        # 等登录检查出结果
        for _ in range(90):
            await pilot.pause(0.5)
            if app.ctx and app.ctx.state.get("xiumi_logged_in") is not None or app._boot_failed:
                break
        await pilot.pause(0.5)
        logged_in = app.ctx.state.get("xiumi_logged_in")
        print("登录判定:", logged_in)

        # 未登录：不弹任何窗，主屏 + 两命令提示
        print("boot 后屏:", type(app.screen).__name__, "（应为 Screen）")
        assert type(app.screen).__name__ == "Screen"
        t = app.query_one("#transcript", Transcript)

        # /login 打开账密屏
        await type_input(app, pilot, "/login")
        await pilot.press("enter")
        await pilot.pause(0.6)
        print("/login 后屏:", type(app.screen).__name__, "（应为 PasswordScreen）")
        assert type(app.screen).__name__ == "PasswordScreen"

        # 空字段点登录 → 本地校验
        await pilot.click("#btn-login")
        await pilot.pause(0.3)

        # 键盘路径：Tab 到登录按钮后 Enter 也可触发（pilot 模拟按键）
        await pilot.click("#acc")
        for ch in "13800000000":
            await pilot.press(ch)
        await pilot.click("#pwd")
        for ch in "wrongpass123":
            await pilot.press(ch)
        await pilot.pause(0.2)

        # 真实提交假凭据：验证填表/勾选/提交/滑块或失败反馈全链路
        events = []
        app.bus.on("captcha_required", lambda et, d: events.append("captcha"))
        app.bus.on("login_result", lambda et, d: events.append(("result", d.get("ok"))))
        await pilot.click("#btn-login")
        # 观察窗口：提交 → 可能滑块提示 → 轮询失败（不等满 90s，8s 后取消观察）
        for _ in range(16):
            await pilot.pause(0.5)
            if any(isinstance(e, tuple) for e in events):
                break
        print("提交后事件:", events)
        # 返回主屏
        await pilot.click("#btn-back")
        for _ in range(6):
            await pilot.pause(0.5)
            if type(app.screen).__name__ != "PasswordScreen":
                break
        print("返回后屏:", type(app.screen).__name__)

        # 状态栏与提示行
        svg = app.export_screenshot()
        import re, html
        texts = [html.unescape(x).replace("\xa0", " ") for x in re.findall(r'>([^<>]+)</text>', svg)]
        ok_two_cmds = any("/login" in x and "/model" in x for x in texts)
        print("两命令提示行:", ok_two_cmds)
        print("无括号补充文案（欢迎卡速查）:", any("设置模型" in x for x in texts) and not any("（如" in x for x in texts))
        print("TUI_SMOKE_OK")


if __name__ == "__main__":
    asyncio.run(main())
