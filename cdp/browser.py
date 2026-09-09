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
    async def ensure_started(self, start_url: str = "about:blank") -> None:
        """端口活着就复用已有 Edge；否则用独立 profile 启动一个。

        start_url 作为首个标签页地址——传入业务 URL 可同时抑制 Edge 的会话恢复
        （Chromium 带 cmdline URL 时不恢复上次标签，避免攒出空页）。
        """
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
            start_url,
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
    async def _close_extra(self, keep_id: str, url_contains: str) -> None:
        """循环关闭多余标签（空白页 + 同域重复页），保持单一工作标签。

        Edge 会话恢复是异步的，需复查到稳定；会话记录随之收敛，
        之后冷启动不会再恢复出一堆旧标签。
        """
        import asyncio

        for _ in range(4):
            pages = await self.cdp.list_pages()
            extra = [
                p
                for p in pages
                if p.get("targetId") != keep_id
                and (p.get("url", "").rstrip("/").startswith("about:blank") or url_contains in p.get("url", ""))
            ]
            if not extra:
                return
            for p in extra:
                try:
                    await self.cdp.send("Target.closeTarget", {"targetId": p["targetId"]})
                except Exception:
                    pass
            await asyncio.sleep(0.6)

    async def get_or_create_tab(self, url_contains: str = "xiumi.us", default_url: str = "https://xiumi.us/") -> Tab:
        """找 url 含 url_contains 的标签页；没有则复用/新建一个，并收敛到单一工作标签。"""
        if not self.cdp:
            raise BrowserNotReady("CDP 未连接")
        pages = await self.cdp.list_pages()
        for p in pages:
            url = p.get("url", "")
            if url_contains in url and "devtools" not in url:
                tab = await self.attach_tab(p)
                await self._close_extra(p["targetId"], url_contains)
                return tab
        # 没有 xiumi 标签：优先复用一个空白标签（navigate 带加载等待），避免新开
        blank = next(
            (p for p in pages if p.get("url", "").rstrip("/") in ("about:blank", "")),
            None,
        )
        if blank is not None:
            tab = await self.attach_tab(blank)
            await tab.navigate(default_url)
            await self._close_extra(blank["targetId"], url_contains)
            return tab
        page = await self.cdp.new_tab(default_url)
        tab = await self.attach_tab(page)
        await tab.navigate(default_url)
        await self._close_extra(page["targetId"], url_contains)
        return tab

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
