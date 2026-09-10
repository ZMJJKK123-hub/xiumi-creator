"""真实凭据登录端到端（人机协同版）：提交前弹出浏览器窗口，等待人工完成滑块。

用法: python scripts/login_e2e2.py <账号> <密码>
流程: 弹出 Edge 窗口 → 填账号密码 → 提交 → 滑块弹出 → 【请人工拖动滑块】→ 轮询登录结果 180 秒。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tui.app import XiumiAgentApp
from tui.widgets import TaskInput


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

        await pilot.click("#task")
        inp = app.query_one("#task", TaskInput)
        inp.value = "/login"
        await pilot.press("enter")
        await pilot.pause(0.8)

        # 提交前先把 Edge 窗口弹出（人工拖滑块用）
        await app.browser.set_window_state(app.ctx.tab, "normal")
        await pilot.pause(0.5)

        await pilot.click("#acc")
        for ch in account:
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause(0.3)
        await pilot.click("#pwd")
        for ch in password:
            await pilot.press(ch)
        await pilot.press("enter")  # 提交
        print("已提交。请在弹出的 Edge 窗口拖动滑块完成验证（等待 180 秒）...")

        result = False
        for i in range(360):
            await pilot.pause(0.5)
            if app.ctx.state.get("xiumi_logged_in"):
                result = True
                break
            url = await app.ctx.tab.current_url()
            if "/auth" not in url:
                result = True
                break
            if i in (60, 120):
                print(f"...仍在等待人工拖动滑块（{i // 2}s）")
        url = await app.ctx.tab.current_url()
        print("最终 URL:", url)
        print("登录结果:", "✅ 成功" if result or "/auth" not in url else "❌ 未成功")
        out = Path(__file__).parent.parent / "recon" / "login_e2e2_edge.png"
        out.parent.mkdir(exist_ok=True)
        await app.ctx.tab.screenshot(path=out)
        print("Edge 截图:", out)


if __name__ == "__main__":
    asyncio.run(main())
