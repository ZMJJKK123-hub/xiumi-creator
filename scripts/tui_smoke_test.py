"""TUI 无头冒烟测试：验证启动链路（配置→Edge→CDP→插件→登录检查→登录屏）。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tui.app import XiumiAgentApp
from tui.widgets import Transcript


async def main() -> None:
    app = XiumiAgentApp()
    async with app.run_test(size=(100, 40)) as pilot:
        # 等启动链路完成（Edge 复用已运行实例，应该很快）
        for _ in range(60):
            await pilot.pause(0.5)
            if app.actions or app._boot_failed:
                break
        print("actions:", sorted(app.actions))
        print("tools:", len(app.registry.names()), "个")
        print("tab:", app.ctx.tab.target_info.get("url") if app.ctx and app.ctx.tab else None)
        transcript = app.query_one("#transcript", Transcript)
        assert transcript is not None
        # 未登录时应弹出登录屏（等登录检查完成，最多 30s）
        for _ in range(60):
            await pilot.pause(0.5)
            if type(app.screen).__name__ in ("LoginScreen",) or app._boot_failed:
                break
        print("current screen:", type(app.screen).__name__)
        assert type(app.screen).__name__ == "LoginScreen", f"期望 LoginScreen，实际 {type(app.screen).__name__}"
        # 账密屏切换
        await pilot.click("#btn-pwd")
        await pilot.pause(0.5)
        print("after #btn-pwd screen:", type(app.screen).__name__)
        assert type(app.screen).__name__ == "PasswordScreen"
        await pilot.click("#btn-back")
        await pilot.pause(0.5)
        # 跳过登录回主屏
        await pilot.click("#btn-skip")
        for _ in range(6):
            await pilot.pause(0.5)
            if type(app.screen).__name__ != "LoginScreen":
                break
        print("after skip screen:", type(app.screen).__name__)
        # 流水写入样式检查
        transcript.write_user("测试任务输入")
        transcript.write_action("browser_click", {"ref": 3})
        transcript.write_result("browser_click", "已点击 ref=3")
        transcript.write_assistant("这是回复。")
        print("TUI_SMOKE_OK")


if __name__ == "__main__":
    asyncio.run(main())
