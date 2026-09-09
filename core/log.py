"""统一日志配置：项目级 logger 工厂，落地到数据目录的滚动文件。

Rule2 §5 基线：应用内禁止 print 追踪运行轨迹，统一经 get_logger() 获取 logger；
级别语义 DEBUG/INFO/WARNING/ERROR；日志文件位于 XIUMI_HOME/logs/app.log。
"""
from __future__ import annotations

import logging  # 标准日志框架，提供 Logger/Handler/格式化能力
import logging.handlers  # RotatingFileHandler，按大小滚动防止日志无限增长
from pathlib import Path  # 路径类型，用于拼接日志目录

# 模块级已初始化 logger 缓存，避免重复添加 Handler
_configured: bool = False

# 单文件 1MB，保留 3 个历史滚动文件
_MAX_BYTES = 1 * 1024 * 1024
_BACKUP_COUNT = 3

# 统一格式：时间 | 级别 | 模块 | 消息
_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    """初始化项目根 logger "xiumi"。

    Globals Used: _configured（防重复初始化标记）。
    Calls: logging.getLogger / logging.handlers.RotatingFileHandler。
    Args: log_dir 日志目录，不存在则创建; level 根级别，默认 INFO。
    Returns: 根 logger 实例，子模块经 get_logger() 继承其配置。
    """
    global _configured
    root = logging.getLogger("xiumi")
    if _configured:
        return root
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log", maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True
    return root


def get_logger(name: str) -> logging.Logger:
    """获取 "xiumi." 前缀的子 logger。

    Globals Used: None。
    Calls: logging.getLogger（继承根配置；未初始化时仅返回实例，不落盘）。
    Args: name 子模块名，建议传 __name__。
    Returns: 带层级命名的 Logger。
    """
    short = name.split(".")[-1] if "." in name else name
    return logging.getLogger(f"xiumi.{short}")
