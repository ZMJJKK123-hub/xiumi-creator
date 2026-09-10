"""命令路由：斜杠命令的注册与分发（策略表，替代 if-elif 链）。

Rule1 §6.2 OCP：新增命令 = 新增处理器并 register，不改分发核心。
"""
from __future__ import annotations

from pathlib import Path  # /file 的路径校验
from typing import Any, Awaitable, Callable  # 处理器与宿主类型标注

from core.agent import Agent  # /model 触发 Agent 的 LLM 客户端重建
from core.config import persist_env  # /model 持久化模型到 .env
from core.llm import LLMClient  # /model 重建 LLM 客户端
from tui.screens import PasswordScreen  # /login 打开账密屏

# 命令处理器签名：接收宿主 App 与用户输入原文，返回是否已消费
Handler = Callable[[Any, str], Awaitable[bool]]


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
    """/model：查看或切换模型；切换即重建 LLM 客户端并写入 .env。

    Args: app 宿主; raw 原始输入（可带模型名参数）。Returns: 恒 True。
    Calls: persist_env / LLMClient / Agent / app.apply_model。
    """
    parts = raw.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        current = app.config.model if app.config else "?"
        key_state = "已配置" if (app.config and app.config.llm_ready) else "未配置"
        app._chat("system", f"当前模型: {current}，{key_state}。用法: /model 模型名")
        return True
    name = parts[1].strip()
    try:
        env_path = persist_env("MODEL", name)
        extra = f"，已写入 {env_path}"
    except Exception as exc:  # noqa: BLE001 写配置失败不阻断会话内切换
        extra = f"，写入 .env 失败: {exc}"
        app.logger.warning("persist_env 失败: %s", exc)
    app.apply_model(name)
    app._chat("system", f"模型已切换为 {name}{extra}")
    return True


def _masked(value: str) -> str:
    """凭据脱敏显示：仅保留首尾各 4 字符。

    Args: value 原始凭据。Returns: 脱敏文本，短值全掩码。
    """
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


async def _cmd_key(app: Any, raw: str) -> bool:
    """/key：设置 API Key（立即生效并写入 .env，输入会脱敏回显）。

    Args: app 宿主; raw 原始输入（含 key 参数）。Returns: 恒 True。
    Calls: persist_env / app.apply_llm_config。
    """
    parts = raw.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        current = app.config.api_key if app.config else ""
        shown = f"{_masked(current)}" if current else "未设置"
        app._chat("system", f"当前 Key: {shown}\n用法: /key 你的API密钥")
        return True
    key = parts[1].strip()
    try:
        persist_env("OPENAI_API_KEY", key)
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("persist_env 失败: %s", exc)
    app.apply_llm_config(api_key=key)
    app._chat("system", f"Key 已设置 {_masked(key)}，立即生效")
    return True


async def _cmd_url(app: Any, raw: str) -> bool:
    """/url：设置 API 接口地址（OpenAI 兼容，立即生效并写入 .env）。

    Args: app 宿主; raw 原始输入（含地址参数）。Returns: 恒 True。
    Calls: persist_env / app.apply_llm_config。
    """
    parts = raw.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        current = app.config.base_url if app.config else ""
        app._chat("system", f"当前地址: {current or '未设置'}\n用法: /url 接口地址，如 /url https://api.deepseek.com")
        return True
    url = parts[1].strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        app._chat("system", "地址需以 http:// 或 https:// 开头")
        return True
    try:
        persist_env("OPENAI_BASE_URL", url)
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("persist_env 失败: %s", exc)
    app.apply_llm_config(base_url=url)
    app._chat("system", f"接口地址已设置为 {url}")
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
            "/key": _cmd_key,
            "/url": _cmd_url,
            "/shot": _cmd_shot,
            "/file": _cmd_file,
        }

    def register(self, name: str, handler: Handler) -> None:
        """注册新命令（扩展点）。

        Args: name 命令名含斜杠; handler 处理器。Returns: None。
        """
        self._routes[name] = handler

    async def dispatch(self, app: Any, raw: str) -> bool:
        """尝试按命令分发用户输入。

        Args: app 宿主; raw 原始输入。Returns: True=已消费，不再当任务处理。
        """
        token = raw.split(maxsplit=1)[0] if raw.startswith(("/", "?")) else ""
        token = "/help" if token == "?" else token
        handler = self._routes.get(token)
        if handler is None:
            return False
        return await handler(app, raw)
