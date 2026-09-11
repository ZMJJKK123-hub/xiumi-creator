"""命令路由：斜杠命令的注册与分发（策略表，替代 if-elif 链）。

Rule1 §6.2 OCP：新增命令 = 新增处理器并 register，不改分发核心。
"""
from __future__ import annotations

from pathlib import Path  # /file 的路径校验
from typing import Any, Awaitable, Callable  # 处理器与宿主类型标注

from tui.screens import PasswordScreen  # /login 打开账密屏

# 命令处理器签名：接收宿主 App 与用户输入原文，返回是否已消费
Handler = Callable[[Any, str], Awaitable[bool]]

# 命令名到一句话描述：自动补全候选与帮助共用
COMMAND_INFO = {
    "/model": "配置模型、Key、地址",
    "/file": "载入任务文件",
    "/login": "登录秀米",
    "/shot": "截图",
    "/help": "帮助",
}


async def _cmd_login(app: Any, raw: str) -> bool:
    """/login：打开账密登录屏。

    Args: app 宿主; raw 原始输入。Returns: 恒 True。
    Calls: app.push_screen / app._chat。
    """
    if app.actions:
        app.push_screen(PasswordScreen())
    else:
        app._chat("system", "插件尚未就绪，稍等片刻再试")
    return True


async def _cmd_help(app: Any, raw: str) -> bool:
    """/help 或 ?：打开快捷键帮助浮层。

    Args: app 宿主; raw 原始输入。Returns: 恒 True。Calls: app.open_help。
    """
    app.open_help()
    return True


async def _cmd_model(app: Any, raw: str) -> bool:
    """/model：打开模型配置屏（模型名、API Key、接口地址同屏填写保存）。

    Args: app 宿主; raw 原始输入（参数被忽略，统一走配置屏）。Returns: 恒 True。
    Calls: app.push_screen(ModelConfigScreen)。
    """
    from tui.screens import ModelConfigScreen  # 局部导入：避免循环依赖

    app.push_screen(ModelConfigScreen())
    return True




async def _cmd_shot(app: Any, raw: str) -> bool:
    """/shot：截取当前页面到 screenshots 目录。

    Args: app 宿主; raw 原始输入。Returns: 恒 True。Calls: app.run_worker / app.quick_shot。
    """
    if app.ctx and app.ctx.tab:
        app.run_worker(app.quick_shot(), thread=False)
    else:
        app._chat("system", "浏览器尚未就绪，无法截图")
    return True


async def _cmd_file(app: Any, raw: str) -> bool:
    """/file：载入 Markdown 任务文件并回显展开内容。

    Args: app 宿主; raw 原始输入（含路径参数）。
    Returns: 参数无效时 True；载入成功返回 False 交由任务流继续。
    Calls: Path.read_text / app.transcript().write_user / app._chat。
    """
    parts = raw.split(maxsplit=1)
    if len(parts) < 2:
        app._chat("system", "用法: /file 路径/到/task.md")
        return True
    path = Path(parts[1].strip(chr(34)))
    if not path.exists():
        app._chat("system", f"文件不存在: {path}")
        return True
    content = path.read_text(encoding="utf-8")
    app.transcript().write_user(content)
    app._chat("system", f"已载入 {path}（{len(content)} 字符）")
    return False  # 内容作为任务继续提交流程


class CommandRouter:
    """斜杠命令路由器。

    职责：识别并分发斜杠命令；未命中或处理器返回 False 时交回任务流。
    属性：_routes 命令名到处理器的映射表。
    生命周期：App 构造时创建；register 为运行期扩展点。
    """

    def __init__(self) -> None:
        self._routes: dict[str, Handler] = {
            "/login": _cmd_login,
            "/help": _cmd_help,
            "/model": _cmd_model,
            "/shot": _cmd_shot,
            "/file": _cmd_file,
        }

    @property
    def command_info(self) -> dict[str, str]:
        """命令描述表（补全候选用）。Args: None。Returns: name->desc 字典。"""
        return COMMAND_INFO

    def register(self, name: str, handler: Handler) -> None:
        """注册新命令（扩展点）。

        Args: name 命令名含斜杠; handler 处理器。Returns: None。
        """
        self._routes[name] = handler

    async def dispatch(self, app: Any, raw: str) -> bool:
        """尝试按命令分发用户输入。

        Args: app 宿主; raw 原始输入。Returns: True=已消费，不再当任务处理。
        """
        token = raw.split(maxsplit=1)[0] if raw.startswith("/") else ""
        handler = self._routes.get(token)
        if handler is None:
            return False
        return await handler(app, raw)
