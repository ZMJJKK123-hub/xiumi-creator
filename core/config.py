"""全局配置：从 .env 与环境变量加载，附 Edge 路径自动探测。

数据目录解析（安装为全局包后开箱即用）：
- 源码目录运行（dev，main.py 在项目根）：数据（.env / .edge-profile / screenshots）留在项目内；
- pip 安装运行（site-packages）：数据放 ~/.xiumi-agent/，首次运行自动生成 .env 模板；
- 可用环境变量 XIUMI_HOME 覆盖数据目录。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # 安装模式下是 site-packages
# 源码目录必有 pyproject.toml；wheel 只装声明的包与模块，不会带上它
IS_DEV = (PROJECT_ROOT / "pyproject.toml").exists()
XIUMI_HOME = Path(os.getenv("XIUMI_HOME", "")) if os.getenv("XIUMI_HOME", "") else (
    PROJECT_ROOT if IS_DEV else Path.home() / ".xiumi-agent"
)

_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

ENV_TEMPLATE = """# xiumi-agent 配置（首次运行自动生成，编辑后重启生效）
# ===== LLM (OpenAI 兼容接口) =====
# 模型由 /model 命令设置，或在此填写
OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
OPENAI_API_KEY=
MODEL=

# ===== 浏览器 =====
# 留空则自动探测常见 Edge 安装路径
EDGE_PATH=
CDP_PORT=9222

# ===== Agent =====
MAX_STEPS=40
"""


def detect_edge() -> str | None:
    """按 环境变量 → 常见路径 → LOCALAPPDATA 顺序探测 Edge。"""
    env = os.getenv("EDGE_PATH", "").strip('"')
    if env and Path(env).exists():
        return env
    for p in _EDGE_CANDIDATES:
        if Path(p).exists():
            return p
    local = os.getenv("LOCALAPPDATA")
    if local:
        p = Path(local) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if p.exists():
            return str(p)
    return None


@dataclass
class Config:
    # LLM
    base_url: str
    api_key: str
    model: str
    # 浏览器
    edge_path: str | None
    cdp_port: int
    profile_dir: Path
    screenshots_dir: Path
    # Agent
    max_steps: int
    tool_result_max_chars: int = 6000

    @property
    def llm_ready(self) -> bool:
        """key、接口地址、模型名三者齐备才算就绪（模型由 /model 设置，无默认值）。"""
        return bool(self.api_key) and bool(self.base_url) and bool(self.model)


def persist_env(key: str, value: str) -> Path:
    """把单个配置项写回生效中的 .env（不存在则先落模板）。返回 env 文件路径。"""
    env_file = XIUMI_HOME / ".env"
    if not env_file.exists() and IS_DEV:
        legacy = PROJECT_ROOT / ".env"
        if legacy.exists():
            env_file = legacy
    if not env_file.exists():
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text(ENV_TEMPLATE, encoding="utf-8")
    lines = env_file.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    hit = False
    for ln in lines:
        if ln.startswith(f"{key}="):
            out.append(f"{key}={value}")
            hit = True
        else:
            out.append(ln)
    if not hit:
        out.append(f"{key}={value}")
    env_file.write_text("\n".join(out) + "\n", encoding="utf-8")
    return env_file


def load_config() -> Config:
    # .env 发现顺序：数据目录 → （dev 模式）项目根
    env_file = XIUMI_HOME / ".env"
    if not env_file.exists() and IS_DEV:
        legacy = PROJECT_ROOT / ".env"
        if legacy.exists():
            env_file = legacy
    if not env_file.exists() and not IS_DEV:
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text(ENV_TEMPLATE, encoding="utf-8")  # 首次运行生成模板
    if env_file.exists():
        load_dotenv(env_file)

    cfg = Config(
        base_url=os.getenv("OPENAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
        api_key=os.getenv("OPENAI_API_KEY", ""),
        model=os.getenv("MODEL", ""),
        edge_path=detect_edge(),
        cdp_port=int(os.getenv("CDP_PORT", "9222")),
        profile_dir=XIUMI_HOME / ".edge-profile",
        screenshots_dir=XIUMI_HOME / "screenshots",
        max_steps=int(os.getenv("MAX_STEPS", "40")),
    )
    cfg.screenshots_dir.mkdir(parents=True, exist_ok=True)
    return cfg
