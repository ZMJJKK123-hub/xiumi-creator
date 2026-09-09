# 自测指南

## 安装与一次性准备

```powershell
pip install git+https://github.com/ZMJJKK123-hub/xiumi-creator.git   # 远程一条命令安装
notepad %USERPROFILE%\.xiumi-agent\.env                            # 首次运行 xiumi 后自动生成，填 OPENAI_API_KEY
xiumi                                                               # 任意目录直接进
```

首次启动自动在后台拉起 Edge（窗口最小化不打扰）→ 弹登录窗口，**账号密码在终端内输入**；如遇滑块验证码，浏览器窗口会自动弹出，拖完自动缩回。登录一次长期保留。

**登录成功后强烈建议做一次编辑器踩点**（当前编辑器选择器是启发式，踩点后更稳）：
在 `scripts/recon.py` 的 `TARGETS` 里加一行（去掉注释）：`("editor", "https://xiumi.us/studio/v5"),`，然后：

```powershell
python main.py recon
```

把 `recon/editor_outline.json` 里确认的选择器更新到 `plugins/xiumi_editor/selectors.json`。

## 逐项测试清单

### 启动与登录
- [ ] 欢迎卡：橙色圆角框、标题嵌上边框、左栏 Welcome back!/模型/目录，右栏「命令与快捷键」速查
- [ ] 未登录时弹登录窗（居中、深色按钮）；「账号密码登录」→ 填入 → 返回 → 「跳过」仍可点击（不卡死）
- [ ] 账密登录：终端输入账号密码，浏览器全程后台（滑块时才弹出）

### 输入与命令
- [ ] 输入任务回车 → 灰底 `> 任务` 命令条回显
- [ ] `/file examples/task.md` → 命令条折叠显示 `⏎ …(N 行)`（先把示例里的图片路径改成真实存在的）
- [ ] `/shot` → 截图路径回显；`/login` → 登录窗弹出；`/file 不存在.md` → 红色 `X` 错误行
- [ ] 空输入/纯空格回车 → 无任何输出且输入框被清空
- [ ] 纯空格状态按 `?` → 帮助浮层（输入非空时 `?` 是普通字符）

### Agent 任务（需 .env 已配）
- [ ] 输入「写一篇秋天咖啡店探店推文，主色暖棕」→ spinner（橙符号+动词+秒数）+ 底栏变「esc 中断任务」
- [ ] 工具行 `└ 工具名(参数)`、结果灰字折叠、空结果 `(no content)`
- [ ] 任务中按 `esc` → 立即中断并显示提示；中断后再提交新任务正常
- [ ] 完成后汇总 + `✻ 共 N 次工具调用` 统计行，底栏回到「? 快捷键」

### 快捷键
- [ ] `↑/↓` 翻输入历史（连按不越界，↓ 到底恢复未提交草稿）
- [ ] `ctrl+l` 清屏重绘欢迎卡；`ctrl+q` 退出

### 任务后检查
- [ ] Edge 里秀米草稿已保存：标题、正文块、图片位置正确
- [ ] `screenshots/` 下有预览截图

## 排错

| 现象 | 处理 |
|---|---|
| 启动失败「端口 9222」 | 关掉残留 Edge（任务管理器搜 msedge）后重跑 |
| 编辑器操作总失败 | 重跑 `python main.py recon` 更新选择器（秀米改版了） |
| 改了代码想快速自检 | `python scripts/tui_smoke_test.py`（无头一键回归，不弹窗） |
