"""真实凭据登录端到端验证（无头驱动真实 Edge）。

用法: python scripts/login_e2e.py <账号> <密码>
流程: /login → 账密屏 → 填入真实凭据 → Enter 提交 → 轮询登录结果（最长 150 秒）。
结束: 截图 Edge 当前页面到 recon/login_e2e_edge.png。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tui.app import XiumiAgentApp
from textual.widgets import Input


async def main() -> None:
    account, password = sys.argv[1], sys.argv[2]
    app = XiumiAgentApp()
    async with app.run_test(size=(110, 30)) as pilot:
        for _ in range(90):
            await pilot.pause(0.5)
            if app.actions or app._boot_failed:
                break
        for _ in range(90):
            await pilot.pause(0.5)
            if app.ctx.state.get("xiumi_logged_in") is not None:
                break
        print("boot 登录判定:", app.ctx.state.get("xiumi_logged_in"))

        await pilot.click("#task")
        inp = app.query_one("#task", Input)
        inp.value = "/login"
        await pilot.press("enter")
        await pilot.pause(0.8)

        await pilot.click("#acc")
        for ch in account:
            await pilot.press(ch)
        await pilot.press("enter")  # 跳到密码框
        await pilot.pause(0.3)
        await pilot.click("#pwd")
        for ch in password:
            await pilot.press(ch)
        await pilot.press("enter")  # 提交登录
        print("凭据已提交，轮询登录结果（最长 150 秒）...")

        result = None
        for _ in range(300):
            await pilot.pause(0.5)
            if app.ctx.state.get("xiumi_logged_in"):
                result = True
                break
            url = await app.ctx.tab.current_url()
            if "/auth" not in url:
                result = True
                break
        url = await app.ctx.tab.current_url()
        print("最终 URL:", url)
        print("登录结果:", "成功" if result or "/auth" not in url else "未成功/仍在验证")
        out = Path(__file__).parent.parent / "recon" / "login_e2e_edge.png"
        out.parent.mkdir(exist_ok=True)
        await app.ctx.tab.screenshot(path=out)
        print("Edge 截图:", out)
        print("TUI 登录态:", app.ctx.state.get("xiumi_logged_in"))


if __name__ == "__main__":
    asyncio.run(main())
