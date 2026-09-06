# xiumi-agent

终端 TUI 形态的公众号排版 Agent：通过 CDP 直接驱动你本机的 **Edge** 打开 **秀米（xiumi.us）**，由 LLM 调用插件工具自动完成「写稿 → 排版 → 插图 → 保存草稿」。

## 架构

```
TUI (Textual) ──事件总线──▶ Agent 主循环 (OpenAI 兼容 function calling)
                                  │ 工具调用
                            插件管理器（browser / xiumi_login / xiumi_editor）
                                  │ JS 模拟用户操作 + CDP 特例(截图/上传文件/真实按键)
                          Edge (msedge.exe, 独立 profile, CDP 9222)
```

- **插件化**：核心只有主循环+注册表；所有网页能力都是 `plugins/*/plugin.py` 里的 Plugin，挂载即用
- **凭据安全**：账号密码只在 TUI 模态框输入，直达登录插件执行，不进 LLM 上下文
- **选择器可维护**：`plugins/*/selectors.json` 集中管理，`recon` 踩点后直接改 JSON

## 快速开始

**方式一：一条命令远程安装（推荐，无需克隆）**

```powershell
pip install git+https://github.com/ZMJJKK123-hub/xiumi_agent.git
xiumi                      # 任意目录、任意终端直接进入 TUI
```

首次运行会在 `~/.xiumi-agent/.env` 自动生成配置模板，填入 `OPENAI_API_KEY` 后重启即可。

**方式二：源码运行**

```bash
git clone https://github.com/ZMJJKK123-hub/xiumi_agent.git
cd xiumi_agent
pip install -r requirements.txt
pip install -e .            # 安装全局命令 xiumi（一次性）
copy .env.example .env      # 填 OPENAI_API_KEY / OPENAI_BASE_URL / MODEL
xiumi                       # 或 python main.py
```

`xiumi recon` = 页面踩点，`xiumi version` = 版本。

首次使用：TUI 弹出登录窗口 → 选「微信扫码」（二维码图片自动弹出）或「账号密码」→ 登录一次长期保留。

## 用法

```
输入任务回车：写一篇秋天咖啡店探店推文，主色暖棕，结尾引导关注
/file examples/task.md      载入文件任务（支持 [img:路径] 图片位置标记）
/login                      重新打开登录窗口
/shot                       截图当前页面
Ctrl+Q 退出 · Ctrl+L 清屏
```

任务两种姿势：
- **全自动**：只给主题 → Agent 写全文 + 排版 + 保存
- **只排版**：给正文 → Agent 只做排版加工

图片：在正文任意位置写 `[img:D:\pics\a.jpg]`，Agent 会上传到秀米图库并插入该位置（无需多模态模型）。

## 踩点（重要）

插件里的选择器是启发式默认值。如果页面操作失败，运行：

```bash
python main.py recon        # dump 登录页/首页 DOM 树 + 截图到 recon/
```

人工确认选择器后更新 `plugins/xiumi_login/selectors.json` 与 `plugins/xiumi_editor/selectors.json`。手动登录秀米后，把编辑器 URL 加进 `scripts/recon.py` 的 `TARGETS` 再跑一次即可踩编辑器。

## 目录

```
core/      agent 主循环 / LLM 客户端 / 工具注册表 / 插件契约 / 事件总线
cdp/       CDP 连接 / Edge 管理 / Tab 封装 / 注入式 JS 操作库
tui/       Textual 界面（聊天面板、动作面板、登录/账密模态屏）
plugins/   browser 通用操控 · tool_browser 后台浏览器(dsh适配) · xiumi_login 登录 · xiumi_editor 排版
scripts/   recon.py 页面踩点
```
