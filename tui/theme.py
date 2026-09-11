"""主题与样式：颜色常量、终端 CSS。

Rule2 §1 表现层配置与组件逻辑物理分离；改主题只动这一个文件。
"""
from __future__ import annotations

ACCENT = "#E06C38"        # 主色：暖橙，用于标题/焦点边框/spinner/按钮 hover
DIM_ACCENT = "#a8542f"    # 暗橙：欢迎卡双栏分隔线
GRAY = "#8E8E8E"          # 次级文本：边框/提示/工具结果
RED = "#E05252"           # 错误色：X 前缀行/失败状态
BG = "#0C0C0C"            # 全局背景
SURFACE = "#161616"       # 模态屏/浮层底色
USER_BAR_BG = "#2A2A2A"   # 用户命令条背景
BORDER_MUTED = "#4a4a52"  # 常态边框（登录框/输入框/按钮）

VERSION = "v0.1.1"        # 应用版本号：xiumi version / 欢迎卡标题共用

# 主界面 CSS：布局三区（流水/spinner/输入框）+ 底部状态栏 + 模态屏
APP_CSS = f"""
Screen {{ background: {BG}; }}
#transcript {{
    height: 1fr; padding: 0 1; background: transparent;
    scrollbar-background: #101010;
    scrollbar-background-hover: #161616;
    scrollbar-color: #3a3a3f;
    scrollbar-color-hover: {ACCENT};
    scrollbar-size: 1 1;
}}
#spinner {{ height: auto; padding: 0 1; }}
#suggest-box {{
    display: none; height: auto; margin: 0 1;
    background: #101010; border: round {BORDER_MUTED}; padding: 0 1;
}}
#rule-top, #rule-bot {{ color: {GRAY}; margin: 0 1; }}
#input-box {{ height: auto; padding: 0 1; }}
#prompt-sym {{ width: auto; color: {GRAY}; padding: 0 0 0 1; }}
#task {{ border: none; background: transparent; height: 1; padding: 0; }}
#task:focus {{ background-tint: transparent; }}
#footer {{ height: 1; padding: 0 2; }}
#hint {{ width: auto; height: 1; color: {GRAY}; }}
#info {{ width: 1fr; height: 1; overflow: hidden; text-align: right; color: {GRAY}; }}
#help-box {{ border: round {ACCENT}; background: {SURFACE}; padding: 1 2; margin: 4 12; width: 76; }}
#cfg-box {{ width: 64; height: auto; border: round {BORDER_MUTED}; background: {SURFACE}; padding: 1 2; }}
#cfg-box Button {{
    background: #1f1f1f; color: #e8e8e8;
    border: round {BORDER_MUTED}; text-style: none;
}}
#cfg-box Button:hover, #cfg-box Button:focus {{ border: round {ACCENT}; background: #262626; }}
#cfg-box Horizontal {{ height: auto; }}
#cfg-box Horizontal Button {{ width: 1fr; }}
#cfg-model, #cfg-key, #cfg-url {{ border: tall {BORDER_MUTED}; background: #101010; }}
#cfg-model:focus, #cfg-key:focus, #cfg-url:focus {{ border: tall {ACCENT}; }}
.login-title {{ text-style: bold; color: {ACCENT}; }}
.login-sub {{ color: {GRAY}; margin-bottom: 1; }}
"""
