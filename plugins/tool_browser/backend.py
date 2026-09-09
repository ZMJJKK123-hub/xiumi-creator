"""后台工具箱浏览器的生命周期管理（供 tool_browser 插件与 browser 插件共享）。

状态挂在 ctx.state[STATE_KEY]，主标签页工具通过 background=true 参数复用。
"""
from __future__ import annotations

import asyncio  # 端口轮询间隔
import shutil  # 临时 profile 目录清理
import subprocess  # Edge 进程启动
import tempfile  # 临时用户目录
import uuid  # 实例句柄
from pathlib import Path  # 路径类型

from cdp.connection import CDPConnection  # CDP 连接
from cdp.helpers import Tab  # 页面标签封装
from core.log import get_logger as _log  # 边界异常记录
from core.registry import AppContext  # 全局上下文

# 后台浏览器状态在 ctx.state 中的键
STATE_KEY = "toolbox_browser"

# 启动参数（除地址外全部静默化，避免弹窗与首启向导）
_BASE_ARGS = [
    "--remote-debugging-port=0",
    "--no-first-run", "--no-default-browser-check",
    "--disable-default-apps", "--disable-extensions",
    "--disable-background-networking", "--disable-features=Translate",
    "--remote-allow-origins=*",
]


class AuxBrowserError(RuntimeError):
    """后台浏览器生命周期异常（带用户可读上下文）。"""


def get_aux_tab(ctx: AppContext) -> Tab:
    """返回后台工具箱浏览器的标签页。

    Args: ctx 全局上下文。Returns: Tab。
    Raises: AuxBrowserError 未打开时。
    """
    aux = ctx.state.get(STATE_KEY)
    if not aux:
        raise AuxBrowserError("后台工具箱浏览器未打开；请先调用 browser_open")
    return aux["tab"]


def _spawn_edge(ctx: AppContext, headless: bool) -> tuple:
    """启动临时 profile 的 Edge 进程。

    Args: ctx 配置来源; headless 是否无头。Returns: (proc, user_data_dir)。
    """
    if not ctx.config.edge_path:
        raise AuxBrowserError("未找到 Edge 可执行文件，检查 .env 的 EDGE_PATH")
    user_data_dir = Path(tempfile.mkdtemp(prefix="xiumi-toolbox-"))
    args = [
        ctx.config.edge_path,
        f"--user-data-dir={user_data_dir}",
        *_BASE_ARGS,
        *(["--headless=new"] if headless else []),
        "about:blank",
    ]
    proc = subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    return proc, user_data_dir


async def _wait_devtools_port(proc, port_file: Path) -> int:
    """轮询 DevToolsActivePort 文件直到端口就绪。

    Args: proc 浏览器进程; port_file 端口文件路径。Returns: 调试端口号。
    Raises: AuxBrowserError 进程早退或 10 秒超时。
    """
    for _ in range(100):
        if proc.poll() is not None:
            raise AuxBrowserError("Edge 进程在调试端口就绪前退出了")
        try:
            port = int(port_file.read_text(encoding="utf-8").splitlines()[0].strip())
            if port > 0:
                return port
        except Exception as exc:  # noqa: BLE001 文件未生成或内容不全属轮询常态
            _log.debug("等待端口文件: %s", exc)
        await asyncio.sleep(0.1)
    raise AuxBrowserError("等待 Edge DevTools 端口超时")


async def _open_first_tab(cdp: CDPConnection, url: str) -> Tab:
    """连接首个页面标签并导航到 url。

    Args: cdp 已建立的连接; url 目标地址。Returns: Tab。
    Raises: AuxBrowserError 无可用标签页。
    """
    pages = await cdp.list_pages()
    if not pages:
        raise AuxBrowserError("Edge 没有可用的页面标签页")
    session_id = await cdp.attach(pages[0]["targetId"])
    tab = Tab(cdp, session_id, pages[0])
    await tab.enable()
    await tab.navigate(url)
    return tab


async def open_aux(ctx: AppContext, url: str, headless: bool) -> dict:
    """启动临时 profile 的独立 Edge 并导航到 url（已存在则先关闭）。

    Globals Used: STATE_KEY/_BASE_ARGS（模块常量）。
    Calls: close_aux / _spawn_edge / _wait_devtools_port / _open_first_tab。
    Args: ctx 上下文; url 目标网址; headless 是否无头。
    Returns: 含 handle/url/headless/port 的状态字典。
    """
    await close_aux(ctx)
    proc, user_data_dir = _spawn_edge(ctx, headless)
    port = await _wait_devtools_port(proc, user_data_dir / "DevToolsActivePort")
    cdp = await CDPConnection.connect(port, timeout=15)
    try:
        tab = await _open_first_tab(cdp, url)
    except Exception:
        await cdp.close()
        proc.kill()
        shutil.rmtree(user_data_dir, ignore_errors=True)
        raise
    handle = uuid.uuid4().hex[:12]
    ctx.state[STATE_KEY] = {
        "handle": handle, "proc": proc, "cdp": cdp, "tab": tab,
        "port": port, "user_data_dir": user_data_dir,
    }
    return {"handle": handle, "url": url, "headless": headless, "port": port}


async def close_aux(ctx: AppContext) -> bool:
    """关闭并清理后台浏览器。

    Args: ctx 上下文。Returns: 是否确有实例被关闭。
    """
    aux = ctx.state.pop(STATE_KEY, None)
    if not aux:
        return False
    try:
        await aux["cdp"].close()
    except Exception as exc:  # noqa: BLE001 清理路径失败仅记录
        _log.debug("关闭后台浏览器连接失败: %s", exc)
    try:
        aux["proc"].kill()
    except Exception as exc:  # noqa: BLE001 进程可能已退出
        _log.debug("终止后台浏览器进程失败: %s", exc)
    shutil.rmtree(aux["user_data_dir"], ignore_errors=True)
    return True
