"""系统剪贴板读取：Ctrl+V 粘贴的平台底座。

架构定位：tui 表现层的平台适配件；唯一调用方 widgets.PasteInput.action_paste。
ctypes 直调 Win32 剪贴板 API（CF_UNICODETEXT）——毫秒级、零第三方依赖
（不经 powershell 子进程）；非 Windows 平台返回空串（本项目 Edge 自动化
本就面向 Windows）。Textual 原生 Input.action_paste 只读应用内内存剪贴板，
读不到系统剪贴板——这是配置屏 Ctrl+V 失效的根因，本模块即为补齐。
"""
from __future__ import annotations  # 延迟注解求值（3.9+ 联合类型写法）

import sys  # 平台判断（win32 才绑定 Win32 API）
import time  # 剪贴板被占用时的重试间隔

# Win32 API 绑定与签名声明（64 位下必须显式 restype，防句柄截断）
if sys.platform == "win32":
    import ctypes  # 外部函数接口：直调 user32/kernel32
    from ctypes import wintypes  # Win32 类型定义（HWND/HANDLE 等）

    _user32 = ctypes.WinDLL("user32", use_last_error=True)  # 剪贴板开关与取数
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # 全局内存锁定
    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.CloseClipboard.restype = wintypes.BOOL
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = wintypes.LPVOID
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

_CF_UNICODETEXT = 13  # 剪贴板格式常量：Unicode 文本
_OPEN_RETRIES = 6     # 剪贴板被他进程独占时的打开重试次数
_RETRY_DELAY_S = 0.03  # 每次重试的间隔秒数


def read_clipboard() -> str:
    """读取系统剪贴板文本。

    Globals Used: _user32/_kernel32（模块级 Win32 API 绑定）、_CF_UNICODETEXT。
    Calls: OpenClipboard / GetClipboardData / GlobalLock / GlobalUnlock / CloseClipboard。
    Args: None。Returns: 剪贴板文本；非 Windows、无文本或打开失败返回 ""。
    """
    if sys.platform != "win32":
        return ""
    for _ in range(_OPEN_RETRIES):  # Office 等进程可能短暂独占剪贴板
        if _user32.OpenClipboard(None):
            break
        time.sleep(_RETRY_DELAY_S)
    else:
        return ""
    try:
        handle = _user32.GetClipboardData(_CF_UNICODETEXT)
        if not handle:
            return ""  # 剪贴板里是图片/文件等非文本格式
        ptr = _kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)  # 读到首个 NUL 宽字符为止
        finally:
            _kernel32.GlobalUnlock(handle)
    finally:
        _user32.CloseClipboard()
