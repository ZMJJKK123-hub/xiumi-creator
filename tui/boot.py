"""启动编排：配置加载、Edge/CDP 连接、插件装载、登录检查。

Rule2 §1 业务编排独立于 App 表现层；boot 失败经 App 的提示通道上报。
"""
from __future__ import annotations

from typing import TYPE_CHECKING  # 仅类型标注使用宿主，避免运行期循环导入

from cdp.browser import EdgeBrowser  # 自动化 Edge 的启动与连接
from core.agent import Agent  # 任务执行主循环
from core.config import XIUMI_HOME, load_config  # 配置解析与数据目录
from core.events import Event, EventType  # 强类型事件
from core.llm import LLMClient  # OpenAI 兼容客户端
from core.log import setup_logging  # 统一日志初始化（滚动文件）
from core.registry import AppContext, PluginManager  # 插件装载与工具注册

if TYPE_CHECKING:  # 类型检查期才导入 App，运行期由参数传入
    from tui.app import XiumiAgentApp


async def boot(app: "XiumiAgentApp") -> None:
    """执行完整启动链路。

    Globals Used: None（状态全部挂 app 实例）。
    Calls: _load_and_log / _start_browser / _check_login / _report_login_state。
    Args: app 宿主（提供 bus/_chat/set_status 等通道）。Returns: None。
    """
    app.set_status("启动中")
    app.config = load_config()
    app.ctx.config = app.config  # 保持上下文与宿主持有同一份配置
    setup_logging(XIUMI_HOME / "logs")
    app.transcript().write_welcome(app._welcome_model(), app._welcome_cwd())
    if not app.config.llm_ready:
        app._chat("system", "⚠ 未配置 API Key，编辑 .env 后重启。当前可登录和截图，不能执行任务。")
    if not await _start_browser(app):
        return
    _report_login_state(app, await _check_login(app))


async def _start_browser(app: "XiumiAgentApp") -> bool:
    """启动并连接自动化浏览器，装载插件。

    Args: app 宿主。Returns: 是否成功；失败已提示用户并置 _boot_failed。
    """
    app.set_status("启动 Edge")
    try:
        app.browser = EdgeBrowser(app.config)
        await app.browser.ensure_started(start_url="https://xiumi.us/")
        await app.browser.connect()
        app.ctx.cdp = app.browser.cdp
        app.ctx.tab = await app.browser.get_or_create_tab("xiumi.us", "https://xiumi.us/")
        await app.browser.set_window_state(app.ctx.tab, "minimized")
        await app.plugins.load_all(app.ctx)
        app.actions = app.plugins.actions
    except Exception as exc:  # noqa: BLE001 启动边界：失败必须转为用户可见提示
        app._boot_failed = True
        app.set_status("启动失败", error=True)
        app._chat("system", f"⚠ 浏览器或插件启动失败: {exc}")
        app.logger.error("boot 失败", exc_info=exc)
        return False
    if app.config.llm_ready:
        app.agent = Agent(app.ctx, app.registry, LLMClient(app.config), app.bus)
    app.set_status(f"{app._welcome_model()} · {len(app.registry.names())} tools")
    return True


async def _check_login(app: "XiumiAgentApp") -> bool:
    """登录态检查（异常按未登录处理）。

    Args: app 宿主。Returns: 是否已登录。
    """
    try:
        return bool(await app.actions["xiumi_login.check"]())
    except Exception as exc:  # noqa: BLE001 登录检查失败按未登录处理
        app.logger.warning("登录检查异常: %s", exc)
        return False


def _report_login_state(app: "XiumiAgentApp", logged_in: bool) -> None:
    """按登录态给出提示与状态栏文案。

    Args: app 宿主; logged_in 检查结果。Returns: None。
    """
    if not logged_in:
        app.set_status("未登录")
        app._chat("system", "未登录：/login 登录 · /model 配置模型")
    else:
        app.set_status(f"{app._welcome_model()} · 秀米已登录")
        app._chat("system", "✻ 就绪，输入任务开始。")
    app.logger.info("boot 完成 logged_in=%s tools=%s", logged_in, len(app.registry.names()))


def make_login_result_minimizer(app: "XiumiAgentApp") -> None:
    """订阅登录成功事件：浏览器收回后台。

    Args: app 宿主。Returns: None。
    """

    def _on_login(event: Event) -> None:
        """登录成功回调。Args: event LOGIN_RESULT 事件。"""
        if event.ok:
            app._window.set("minimized")

    app.bus.on(EventType.LOGIN_RESULT, _on_login)
