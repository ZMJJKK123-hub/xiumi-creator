"""Edge 生命周期与标签页管理：基础设施层的"资源池"。

架构定位：cdp 基础设施；上游 tui/boot._start_browser（组装期唯一调用方）；
下游 connection.py（建连）与 helpers.Tab（页面操作）。
产出 AppContext.tab（单标签页收敛），供全部插件工具复用；
独立 profile 保证登录态持久化且不污染用户日常浏览器。
"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

import subprocess  # 拉起 Edge 进程
from typing import Any  # 通用类型标注

from core.config import Config  # Edge 路径/端口/数据目录配置
from core.log import get_logger  # 边界异常记录

from .connection import CDPConnection  # 浏览器级 CDP 连接
from .helpers import Tab  # 标签页高级封装


class BrowserNotReady(RuntimeError):
    """浏览器未就绪错误。

    类职责：标记 Edge 未启动/未连接的边界状态，供上层给出可读提示。
    属性：无附加。生命周期：raise 即弃。
    """

    pass


class EdgeBrowser:
    """Edge 浏览器生命周期与标签页管理。

    类职责：启动/复用自动化 Edge（独立 profile + 调试端口），收敛到单标签页。
    属性：config 注入的配置；cdp 浏览器级连接；_proc 拉起的 Edge 进程。
    生命周期：boot 构造 → ensure_started/connect → get_or_create_tab 取页 → shutdown 回收。
    """

    def __init__(self, config: Config):
        """Args: config 全局配置（Edge 路径/端口/数据目录）。"""
        self.config = config  # 全局配置引用
        self.cdp: CDPConnection | None = None  # 浏览器级 CDP 连接
        self._proc: subprocess.Popen | None = None  # 自行拉起的 Edge 进程

    # ---- 启动 ----
    async def ensure_started(self, start_url: str = "about:blank") -> None:
        """确保自动化 Edge 就绪（端口活着就复用，否则独立 profile 启动）。

        Globals Used: None。Calls: _port_alive / subprocess.Popen / connect。
        Args: start_url 首标签页地址（传业务 URL 可抑制会话恢复攒空页）。
        Returns: None；启动失败 raise BrowserNotReady。
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
            "--start-minimized",  # 后台运行：窗口最小化到任务栏，需要时再调出
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
        """探测调试端口是否已有浏览器。Args: None。Returns: 是否存活。"""
        probe: CDPConnection | None = None
        try:
            probe = await CDPConnection.connect(self.config.cdp_port, timeout=1.5)
            return True
        except Exception as exc:  # noqa: BLE001 探测失败即端口未就绪
            get_logger(__name__).debug("端口探测: %s", exc)
            return False
        finally:
            if probe:
                try:
                    await probe.close()
                except Exception:
                    pass

    async def connect(self) -> None:
        """建立浏览器级 CDP 连接并预取标签页。Calls: CDPConnection.connect。Args: None。Returns: None。"""
        self.cdp = await CDPConnection.connect(self.config.cdp_port)

    # ---- 标签页 ----
    async def _close_extra(self, keep_id: str, url_contains: str) -> None:
        """关闭多余标签页，收敛到单标签。

        Args: keep_id 保留的 targetId; url_contains URL 含此串也保留。Returns: None。
        """
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
                except Exception as exc:  # noqa: BLE001 关闭多余标签失败不影响主流程
                    get_logger(__name__).debug("关闭多余标签失败 %s: %s", p.get("url"), exc)
            await asyncio.sleep(0.6)

    async def get_or_create_tab(self, url_contains: str = "xiumi.us", default_url: str = "https://xiumi.us/") -> Tab:
        """取业务标签页：存在则附加，不存在则新建（统一收敛入口）。

        Globals Used: None。Calls: cdp.list_pages / open_tab / attach_tab。
        Args: url_contains 匹配既有页的 URL 片段; default_url 新建地址。
        Returns: 就绪的 Tab。
        """
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
        """新建标签页并返回 Tab。Calls: cdp.new_tab / attach_tab。Args: url 初始地址。Returns: Tab。"""
        if not self.cdp:
            raise BrowserNotReady("CDP 未连接")
        page = await self.cdp.new_tab(url)
        return await self.attach_tab(page)

    async def attach_tab(self, target_info: dict[str, Any]) -> Tab:
        """附加到既有 target 构造 Tab。Calls: cdp.attach / Tab 构造。Args: target_info 页面元数据。Returns: Tab。"""
        session_id = await self.cdp.attach(target_info["targetId"])
        tab = Tab(self.cdp, session_id, target_info)
        await tab.enable()
        return tab

    async def shutdown(self) -> None:
        """关闭连接（保留浏览器进程与登录态）。Calls: cdp.close。Args: None。Returns: None。"""
        if self.cdp:
            await self.cdp.close()
            self.cdp = None

    # ---- 窗口可见性 ----
    async def set_window_state(self, tab, state: str) -> None:
        """控制浏览器窗口显隐。

        Globals Used: None。Calls: tab.send(Browser.* )。
        Args: tab 业务标签页; state normal/minimized。Returns: None。
        """
        """控制自动化 Edge 主窗口：'minimized'（后台）| 'normal'（前台可见）。

        登录/待命时最小化不打扰用户；任务运行或需要人工滑块时调出。
        """
        if not self.cdp or not tab:
            return
        try:
            res = await self.cdp.send(
                "Browser.getWindowForTarget", {"targetId": tab.target_info.get("targetId")}
            )
            await self.cdp.send(
                "Browser.setWindowBounds",
                {"windowId": res["windowId"], "bounds": {"windowState": state}},
            )
        except Exception as exc:  # noqa: BLE001 窗口控制失败不影响主流程
            get_logger(__name__).debug("set_window_state(%s) 失败: %s", state, exc)
