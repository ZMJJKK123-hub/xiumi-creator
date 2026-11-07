import {Box, Text} from 'ink'; // Model/help surfaces share one constrained dialog area.
import type {ReactElement} from 'react'; // Explicit rendering contract.
import type {EditorState} from './contracts.js'; // Transient form values stay outside transcript storage.
import {COMMANDS} from './command_catalog.js'; // Same command metadata as completion and welcome.
import {summary} from './presentation.js'; // Narrow-dialog text clipping.
import {TaskInput} from './task_input.js'; // Shared selection/caret rendering with password masking.
import {THEME} from './theme.js'; // Consistent border and status colors.

/** Help dialog. Args: width/height. Returns: command and key reference from shared metadata.
 * Globals: COMMANDS/THEME. Calls: summary. Boundary: constrained height clips the reference; Esc closes through App. */
export function HelpDialog({width, height}: {readonly width: number; readonly height: number}): ReactElement {
  const lines = [...COMMANDS.map(command => `${command.name}  ${command.description}`), 'Esc 中断 / 关闭窗口 · Ctrl+Q 退出', 'Ctrl+L 清屏 · PgUp/PgDn 翻页 · End 回到底部', 'Ctrl+O 展开思考 · Alt+←/→ 选择轮次', 'Ctrl+↑/↓ 滚动思考 · Ctrl+V 粘贴', '鼠标滚轮翻页；按住 Shift 使用终端文字选择'];
  return <Box borderStyle="round" borderColor={THEME.accent} flexDirection="column" width={width} height={height} overflow="hidden">
    <Text bold color={THEME.accent}>{summary('命令 / 快捷键（任意键关闭）', width - 2)}</Text>
    {lines.slice(0, Math.max(0, height - 3)).map(line => <Text key={line}>{summary(line, width - 2)}</Text>)}
  </Box>;
}

/** Transient model form. Args: fields/focus/status/bounds. Returns: masked form with explicit preview scope.
 * Globals: THEME. Calls: TaskInput/summary. Boundary: no field value is written to a file or transcript by this component. */
export function ModelDialog({fields, focus, status, width, height}: {
  readonly fields: readonly EditorState[]; readonly focus: number; readonly status: string; readonly width: number; readonly height: number;
}): ReactElement {
  const labels = ['模型', '密钥', '地址'];
  return <Box borderStyle="round" borderColor={THEME.accent} flexDirection="column" width={width} height={height} overflow="hidden">
    <Text bold color={THEME.accent}>{summary('模型配置 · 预览仅保存到内存', width - 2)}</Text>
    {labels.map((label, index) => <Box key={label}><Text>{focus === index ? '›' : ' '} {label}: </Text><TaskInput editor={fields[index] ?? {text: '', cursor: 0, anchor: null}} width={width - 10} masked={index === 1} focused={focus === index}/></Box>)}
    <Text color={THEME.muted}>{summary('Tab 切换 · Enter 下一项/保存 · Esc 取消', width - 2)}</Text>
    <Text color={THEME.error}>{summary(status, width - 2)}</Text>
  </Box>;
}
