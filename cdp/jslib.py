"""注入页面的 JS 操作库加载器：从同目录 jslib.js 资源读取源码。

库内容以 window.__agent 挂载：outline/click/type/press/find/findByText/
getText/focusEnd/pasteHTML/appendHTML/editorInsert/editorInfo/triggerChange。
"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

import json  # 构造 __agent.fn(args) 调用表达式
from pathlib import Path  # 定位包内资源文件

# 资源路径：与本模块同目录（pip 安装后位于 site-packages/cdp/）
_JS_RESOURCE = Path(__file__).resolve().parent / "jslib.js"


def load_agent_js() -> str:
    """读取注入用 JS 源码。

    Globals Used: _JS_RESOURCE（模块级资源路径常量）。
    Calls: Path.read_text。
    Args: None。Returns: str，可在页面 evaluate 的 IIFE 源码，幂等可重复执行。
    """
    return _JS_RESOURCE.read_text(encoding="utf-8")


def call_expr(fn: str, *args) -> str:
    """生成 window.__agent.fn(arg1, ...) 调用表达式。

    Globals Used: None。Calls: json.dumps（参数序列化）。
    Args: fn __agent 方法名; args JSON 可序列化实参。
    Returns: str JS 表达式。
    """
    return f"window.__agent.{fn}(...{json.dumps(list(args), ensure_ascii=False)})"
