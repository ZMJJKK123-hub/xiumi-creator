# xiumi-agent

终端 TUI 形态的公众号排版 Agent：通过 CDP 直接驱动你本机的 **Edge** 打开 **秀米（xiumi.us）**，由 LLM 调用插件工具自动完成「写稿 → 排版 → 插图 → 保存草稿」。

## TypeScript 终端渲染预览

新渲染层使用 **TypeScript strict + React + Ink**，源码位于 `src/terminal_ui/`。
当前阶段可以独立运行和验证界面：消息重排、分轮思考、滚动、命令补全、配置表单、任务文件读取和中断。
界面会明确标注「渲染预览 / 模拟运行」；任务与登录使用模拟数据，模型配置仅在内存生效，截图尚未连接浏览器。
现有真实排版功能继续通过下面的 Python 入口运行。

```powershell
npm ci
npm start -- --demo              # 交互预览；需要真实终端
npm start -- --snapshot          # 输出一帧，可用于重定向或 CI
npm run check                   # strict 类型检查、lint、测试、构建
node ts-dist/main.js --demo      # 构建后直接运行
```

推荐使用本项目验证过的 Node.js 24，其他版本需满足 `package.json` 中的 engines 约束。
输入任务回车可以观察两轮思考与工具事件；`/file "带空格的路径/task.md"` 会读取完整 UTF-8 正文作为任务。
`Ctrl+O` 展开/收起思考，`Alt+←/→` 选择历史轮次，`Ctrl+↑/↓` 在该轮内部滚动；消息区使用滚轮或 PgUp/PgDn，上翻后新消息不会抢走阅读位置，空输入时 End 回到底部。
`Ctrl+L` 清除已完成历史并保留当前任务，Esc 中断任务或关闭浮层，`Ctrl+Q` 退出。

渲染结构、运行服务接入契约和验证范围见 [架构说明](docs/ARCHITECTURE.md)。

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

**方式一：PyPI 直接安装（推荐）**

```powershell
pip install xiumiagent
xiumi                      # 任意目录、任意终端直接进入 TUI
```

首次运行会在 `~/.xiumi-agent/.env` 自动生成配置模板，填入 `OPENAI_API_KEY` 后重启即可。

**方式二：从 GitHub 安装（获取最新开发版）**

```powershell
pip install git+https://github.com/ZMJJKK123-hub/xiumi-creator.git
```

**方式三：源码运行**

```bash
git clone https://github.com/ZMJJKK123-hub/xiumi-creator.git
cd xiumi-creator
pip install -r requirements.txt
pip install -e .            # 安装全局命令 xiumi（一次性）
copy .env.example .env      # 填 OPENAI_API_KEY / OPENAI_BASE_URL / MODEL
xiumi                       # 或 python main.py
```

`xiumi recon` = 页面踩点，`xiumi version` = 版本。

首次使用：未登录时界面会提示 `/login` 与 `/model` 两个命令，`/login` 输入账号密码完成登录，长期保留。

## 用法

```
输入任务回车：写一篇秋天咖啡店探店推文，主色暖棕，结尾引导关注
/model                      配置模型、API Key、接口地址（同屏填写保存）
/file examples/task.md      载入文件任务（支持 [img:路径] 图片位置标记）
/login                      登录秀米
/shot                       截图当前页面
/help                       帮助
输入 / 自动弹出命令候选，Tab 切换，Enter 确定
esc 中断任务 · Ctrl+L 清屏 · Ctrl+Q 退出
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
src/       TypeScript 组合入口 / 严格类型终端渲染 / 平台与日志适配
tests/     TypeScript 状态、运行边界和真实 Ink 组件交互测试
docs/      渲染架构与 RuntimePort 接入契约
cdp/       CDP 连接 / Edge 管理 / Tab 封装 / 注入式 JS 操作库
tui/       Textual 界面（聊天面板、动作面板、登录/账密模态屏）
plugins/   browser 通用操控 · tool_browser 后台浏览器(dsh适配) · xiumi_login 登录 · xiumi_editor 排版
scripts/   recon.py 页面踩点
```
