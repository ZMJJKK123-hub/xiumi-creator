"""浏览器窗口可见性调度：登录等待时弹出，登录结束/取消后收回；任务全程保持后台。"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

import asyncio  # 异步任务派发
from typing import TYPE_CHECKING  # 仅类型标注

from core.log import get_logger  # 边界异常记录

if TYPE_CHECKING:
    from cdp.browser import EdgeBrowser  # 浏览器生命周期
    from core.registry import AppContext  # 上下文（取 tab）


class WindowScheduler:
    """自动化浏览器窗口显隐调度器。

    类职责：把窗口状态切换派发为后台任务，失败仅记日志。
    实例：browser/ctx 由宿主注入引用（读属性，不持有）。
    生命周期：随 App 存在；_set_window 可被任意事件回调触发。
    """

    def __init__(self, app_ref) -> None:
        """绑定宿主 App。

        Args: app_ref 宿主应用（读取其 browser/ctx 属性）。
        """
        self._app = app_ref
        self._log = get_logger("window")

    def set(self, state: str) -> None:
        """派发窗口状态切换（normal/minimized）。Calls: set_window_state（后台任务）。

        Args: state 目标窗口状态。Returns: None。
        """

        async def _go() -> None:
            """窗口状态设置协程。Args: None。Returns: None。"""
            app = self._app
            try:
                if app.browser and app.ctx and app.ctx.tab:
                    await app.browser.set_window_state(app.ctx.tab, state)
            except Exception as exc:  # noqa: BLE001 窗口控制失败不影响主流程
                self._log.debug("set_window_state(%s) 失败: %s", state, exc)

        try:
            asyncio.get_running_loop().create_task(_go())
        except RuntimeError:  # 事件回调外的同步上下文
            self._log.debug("无运行中的事件循环，跳过窗口切换: %s", state)
