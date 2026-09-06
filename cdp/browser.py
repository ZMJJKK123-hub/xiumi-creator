"""Edge 启动与标签页管理（独立自动化 profile）。"""
from __future__ import annotations

import subprocess
from typing import Any

from core.config import Config

from .connection import CDPConnection
from .helpers import Tab


class BrowserNotReady(RuntimeError):
    pass


class EdgeBrowser:
    def __init__(self, config: Config):
        self.config = config
        self.cdp: CDPConnection | None = None
        self._proc: subprocess.Popen | None = None

    # ---- 启动 ----
    async def ensure_started(self) -> None:
        """端口活着就复用已有 Edge；否则用独立 profile 启动一个。"""
        if await self._port_alive():
            return
        if not self.config.edge_path:
            raise BrowserNotReady(
                "未找到 Edge，请在 .env 的 EDGE_PATH 指定 msedge.exe 路径"
            )
        args = [
            self.config.edge_path,
            f"--remote-debugging-port={self.config.cdp_port}",
            f"--user-data-dir={self.config.profile_dir}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
            "--restore-last-session=false",
            "about:blank",
        ]
        self._proc = subprocess.Popen(args, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        for _ in range(80):  # 最多等 20 秒
            if await self._port_alive():
                return
            import asyncio

            await asyncio.sleep(0.25)
        raise BrowserNotReady(f"Edge 调试端口 {self.config.cdp_port} 未就绪")

    async def _port_alive(self) -> bool:
        probe: CDPConnection | None = None
        try:
            probe = await CDPConnection.connect(self.config.cdp_port, timeout=1.5)
            return True
        except Exception:
            return False
        finally:
            if probe:
                try:
                    await probe.close()
                except Exception:
                    pass

    async def connect(self) -> None:
        self.cdp = await CDPConnection.connect(self.config.cdp_port)

    # ---- 标签页 ----
    async def get_or_create_tab(self, url_contains: str = "xiumi.us", default_url: str = "https://xiumi.us/") -> Tab:
        """找 url 含 url_contains 的标签页；找不到就新建并导航到 default_url。"""
        if not self.cdp:
            raise BrowserNotReady("CDP 未连接")
        pages = await self.cdp.list_pages()
        for p in pages:
            url = p.get("url", "")
            if url_contains in url and "devtools" not in url:
                return await self.attach_tab(p)
        page = await self.cdp.new_tab(default_url)
        return await self.attach_tab(page)

    async def open_tab(self, url: str) -> Tab:
        if not self.cdp:
            raise BrowserNotReady("CDP 未连接")
        page = await self.cdp.new_tab(url)
        return await self.attach_tab(page)

    async def attach_tab(self, target_info: dict[str, Any]) -> Tab:
        session_id = await self.cdp.attach(target_info["targetId"])
        tab = Tab(self.cdp, session_id, target_info)
        await tab.enable()
        return tab

    async def shutdown(self) -> None:
        if self.cdp:
            await self.cdp.close()
            self.cdp = None
