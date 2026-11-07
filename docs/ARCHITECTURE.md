# TypeScript 终端渲染层

本轮落地已审核的 Node.js + TypeScript + React + Ink 渲染方案。TS 运行入口为 `src/main.tsx`，Python `main.py` 保持原版真实业务入口。
当前 TS RuntimePort 实现为离线预览；TS Agent、CDP 和秀米工具接入仍属于后续阶段，未使用隐藏的 Python 桥接，也未将模拟结果呈现为真实操作成功。

## 依赖和数据流

运行服务发送 UiEvent → UiController → 纯状态转换 → SessionStore → 纯显示计算 → Ink 组件。
组件产生 UiIntent → UiController 校验 → RuntimePort.dispatch → 接受/拒绝，后续进度继续通过事件发送。
类型定义、状态存储、纯计算、服务调用和终端 I/O 分别放在独立模块。

| 文件 | 职责 |
| --- | --- |
| `src/main.tsx` | 组装预览服务、控制器、日志和终端适配，管理 CLI、信号和退出回收 |
| `src/terminal_ui/contracts.ts` | 唯一 UI 协议、状态和平台接口；所有跨模块载荷有显式类型 |
| `src/terminal_ui/presentation.ts` | 纯事件归约、中文/emoji 换行、可见行投影、选区编辑和滚动锚点 |
| `src/terminal_ui/session_store.ts` | 会话内存快照、50ms 帧合并、按不可变消息对象保存的弱引用排版缓存；缩放时重新排版 |
| `src/terminal_ui/controller.ts` | 输入边界、事件接入、中断、清屏和订阅生命周期 |
| `src/terminal_ui/app.tsx` | 固定屏幕布局、独占输入路由、焦点、浮层、补全和消息滚动 |
| `src/terminal_ui/transcript.tsx` | 只挂载可见消息行；保留完整原文，随终端宽度重新换行 |
| `src/terminal_ui/thinking.tsx` | 忙碌期间的活动提示；思考内容按轮保存在会话中 |
| `src/terminal_ui/task_input.tsx` | 按字素处理光标/选区，宽字符水平滚动，密钥遮蔽 |
| `src/terminal_ui/dialogs.tsx` | 帮助和模型表单；小窗口以当前焦点字段的紧凑表单显示 |
| `src/terminal_ui/command_catalog.ts` | 欢迎区、帮助和补全共享的命令元数据 |
| `src/terminal_ui/terminal_io.ts` | Windows 系统剪贴板、SGR 滚轮分包解析及鼠标模式清理 |
| `src/terminal_ui/theme.ts` | 视觉令牌、刷新间隔、文件大小、任务长度和剪贴板超时 |
| `src/terminal_ui/preview_runtime.ts` | 可中断的两轮离线事件源，UTF-8 文件读取和内存配置验证 |
| `src/infrastructure/log.ts` | 带 traceId 的结构化文件日志；不写用户正文、密钥或原始异常消息 |

## RuntimePort 接入契约

`subscribe(listener)` 返回退订函数；订阅后收到的事件必须有序。
`dispatch(intent)` 返回 Promise<IntentResult>；任务提交返回接受状态后，执行结果仍通过事件回传，不阻塞输入循环。
`close()` 回收后台工作且必须可以重复调用。未来真实服务的适配器在进入此接口前验证外部 JSON，禁止以类型断言替代运行时校验。

| 操作 | 输入 | 结果与约束 |
| --- | --- | --- |
| `submit_task` | 完整任务正文 | 空白或超过 100000 字符拒绝；忙碌时拒绝并保留输入；原文不经显示摘要替换 |
| `interrupt` | 当前任务 ID | UI 进入 cancelling，收到对应 task_finished 才结束忙碌；拒绝取消时恢复 running |
| `load_file` | 本地路径，可带引号或空格 | 返回 task_text，随后以文件正文提交任务；目录、空文件、无权限、非法 UTF-8、超过 2MB 或字符上限均返回可见错误 |
| `save_model` | 模型名、密钥、完整 HTTP(S) 地址 | 所有字段验证通过后才改变安全摘要；地址禁止嵌入账号密码；预览仅保存摘要到内存，不持久化或保存密钥 |
| `login` | 无 | 预览发出明确的模拟成功提示；真实服务以后替换实现 |
| `capture` | 无 | 预览返回 unavailable；没有生成截图文件 |

IntentResult 为 accepted、task_text 或 rejected。rejected.code 为 invalid_input、busy、unavailable、io_error；消息在输入区附近的流水/表单内显示。未预期运行错误记脱敏日志并转 io_error，避免 Promise 异常穿透输入事件。

task_started/task_finished 携带 taskId；message、tool 和 thinking 事件还携带各自稳定 ID。ID 必须在一次会话中唯一。
一次任务以 completed/cancelled/failed 中的一种结果结束；终结会同时收束尚未结束的思考和工具。
旧任务、重复消息/开始事件及终结后的增量被忽略。运行服务只发布语义事件，不能调用组件方法。
model_changed 仅携带模型名、接口地址与是否配置的布尔值；密钥不得出现在状态、消息、回放或日志中。

## 渲染与输入约束

- 原文保存在会话，截断和换行只发生在显示投影。终端控制序列在显示边界清除，防止正文触发终端命令。
- UI 刷新合并不丢弃事件或原始增量；task_finished 立即发布最后一帧。
- 每轮思考独立保留。无思考内容的完成轮次隐藏；Alt+左右选择历史轮次，Ctrl+O 展开，Ctrl+上下在该轮内部滚动。
- 消息上翻后使用消息 ID + 行偏移保持阅读位置；End 在输入为空时恢复贴底跟随。
- 清屏保留活跃任务，已完成记录从会话中清除，不会因之后收到增量再次出现。
- 浮层优先接收按键，补全其次。带参数的命令在输入空格后关闭补全，避免覆盖文件参数。
- 粘贴分为终端括号粘贴与 Ctrl+V 系统剪贴板两条路径；原文只插入一次。系统剪贴板超时/不可用时提示使用终端粘贴。
- 开启鼠标上报后，普通滚轮控制消息滚动；终端原生文本选择通常需要按住 Shift，具体由终端决定。
- 退出时退订输入/事件、取消刷新计时器、结束预览工作，并恢复鼠标、光标、括号粘贴和备用屏幕。

## 验证与当前边界

`npm run check` 依次执行 strict 类型检查、eslint（禁止显式 any/非空断言）、Vitest 和生产构建。
测试覆盖状态机、迟到/重复事件、多轮思考、清屏、刷新合并、Unicode/emoji、选区替换、文件错误分支、配置校验、密钥遮蔽、运行服务异常、日志脱敏、鼠标分包及卸载清理。
真实 Ink 组件覆盖 80×24、110×32、160×50、40×12、20×6；以输入事件验证任务、补全、弹窗、粘贴、滚动和缩放。
Windows ConPTY 已验证编译后启动、中文/emoji 输入、任务完成、Ctrl+O 展开及 Ctrl+Q 正常退出。尚未逐一人工验证 Windows Terminal 与 VS Code 终端的 IME、鼠标和剪贴板差异。

旧 Python 渲染层等真实 TS 后端接入并完成整体验收后再删除。本阶段没有更改 Agent、CDP 或秀米插件。
