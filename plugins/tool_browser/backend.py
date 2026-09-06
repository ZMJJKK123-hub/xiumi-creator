"""后台工具箱浏览器的生命周期管理（供 tool_browser 插件与 browser 插件共享）。

状态挂在 ctx.state[STATE_KEY]，主标签页工具通过 background=true 参数复用。
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from cdp.connection import CDPConnection
from cdp.helpers import Tab
from core.registry import AppContext

STATE_KEY = "toolbox_browser"


class AuxBrowserError(RuntimeError):
    pass


def get_aux_tab(ctx: AppContext) -> Tab:
    """返回后台工具箱浏览器的标签页；未打开则报错。"""
    aux = ctx.state.get(STATE_KEY)
    if not aux:
        raise AuxBrowserError("后台工具箱浏览器未打开；请先调用 browser_open")
    return aux["tab"]


async def open_aux(ctx: AppContext, url: str, headless: bool) -> dict:
    """启动一个临时 profile 的独立 Edge 并导航到 url（已存在则先关闭）。"""
    await close_aux(ctx)
    cfg = ctx.config
    if not cfg.edge_path:
        raise AuxBrowserError("未找到 Edge 可执行文件（检查 .env 的 EDGE_PATH）")

    user_data_dir = Path(tempfile.mkdtemp(prefix="xiumi-toolbox-"))
    args = [
        cfg.edge_path,
        f"--user-data-dir={user_data_dir}",
        "--remote-debugging-port=0",  # 0 = 随机端口，实际端口写入 DevToolsActivePort
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-features=Translate",
        "--remote-allow-origins=*",
        *(["--headless=new"] if headless else []),
        "about:blank",
    ]
    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    # 等 DevToolsActivePort 文件出现（dsh 原版机制）
    import asyncio

    port_file = user_data_dir / "DevToolsActivePort"
    port: int | None = None
    for _ in range(100):
        if proc.poll() is not None:
            shutil.rmtree(user_data_dir, ignore_errors=True)
            raise AuxBrowserError("Edge 进程在调试端口就绪前退出了")
        try:
            first_line = port_file.read_text(encoding="utf-8").splitlines()[0].strip()
            p = int(first_line)
            if p > 0:
                port = p
                break
        except Exception:
            pass
        await asyncio.sleep(0.1)
    if port is None:
        proc.kill()
        shutil.rmtree(user_data_dir, ignore_errors=True)
        raise AuxBrowserError("等待 Edge DevTools 端口超时")

    cdp = await CDPConnection.connect(port, timeout=15)
    try:
        pages = await cdp.list_pages()
        if not pages:
            raise AuxBrowserError("Edge 没有可用的页面标签页")
        session_id = await cdp.attach(pages[0]["targetId"])
        tab = Tab(cdp, session_id, pages[0])
        await tab.enable()
        await tab.navigate(url)
    except Exception:
        await cdp.close()
        proc.kill()
        shutil.rmtree(user_data_dir, ignore_errors=True)
        raise

    handle = uuid.uuid4().hex[:12]
    ctx.state[STATE_KEY] = {
        "handle": handle,
        "proc": proc,
        "cdp": cdp,
        "tab": tab,
        "port": port,
        "user_data_dir": user_data_dir,
    }
    return {"handle": handle, "url": url, "headless": headless, "port": port}


async def close_aux(ctx: AppContext) -> bool:
    """关闭并清理后台浏览器；返回是否确有实例被关闭。"""
    aux = ctx.state.pop(STATE_KEY, None)
    if not aux:
        return False
    try:
        await aux["cdp"].close()
    except Exception:
        pass
    try:
        aux["proc"].kill()
    except Exception:
        pass
    shutil.rmtree(aux["user_data_dir"], ignore_errors=True)
    return True
