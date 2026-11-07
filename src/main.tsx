import {randomUUID} from 'node:crypto'; // Trace ID for structured diagnostics.
import {join} from 'node:path'; // Project-local log directory.
import {render} from 'ink'; // Owns alternate screen, raw input and cursor restoration.
import {createLogger} from './infrastructure/log.js'; // Redacted diagnostics never mix with the terminal UI.
import {TerminalApp} from './terminal_ui/app.js'; // Approved rendering root.
import {UiController} from './terminal_ui/controller.js'; // Connects state and runtime through typed contracts.
import {PreviewRuntime} from './terminal_ui/preview_runtime.js'; // Explicit offline runtime until the TS backend is available.
import {createTerminalPort} from './terminal_ui/terminal_io.js'; // Clipboard and wheel platform adapter.
import {DEFAULT_UI_CONFIG} from './terminal_ui/theme.js'; // Central refresh/file/clipboard configuration.

/** CLI composition root. Args: process CLI flags. Returns: exit promise; --help prints usage, --snapshot renders once.
 * Globals: process/DEFAULT_UI_CONFIG. Calls: render/controller.close. Boundary: non-TTY interactive launches fail clearly; signals/failures always dispose resources. */
async function main(): Promise<void> {
  const args = process.argv.slice(2);
  if (args.includes('--help')) { process.stdout.write('xiumi terminal UI preview\n  npm start -- --demo      offline interactive preview\n  npm start -- --snapshot  print a non-interactive frame\n  Python production entry: python main.py\n'); return; }
  if (args.some(arg => !['--demo', '--snapshot'].includes(arg))) throw new Error('Unknown option; use --help');
  const snapshot = args.includes('--snapshot');
  if (!snapshot && (!process.stdin.isTTY || !process.stdout.isTTY)) throw new Error('Interactive preview requires a terminal; use --snapshot for redirected output');
  const logger = createLogger(join(process.cwd(), 'logs'), randomUUID());
  const runtime = new PreviewRuntime(DEFAULT_UI_CONFIG);
  const controller = new UiController(runtime, DEFAULT_UI_CONFIG, logger);
  const terminal = createTerminalPort(process.stdin, process.stdout, DEFAULT_UI_CONFIG);
  controller.notice('TypeScript 渲染预览：输入任意任务体验两轮思考；/help 查看命令。');
  controller.store.flush();
  const instance = render(<TerminalApp controller={controller} terminal={snapshot ? {readClipboard: terminal.readClipboard, subscribeWheel: () => () => undefined} : terminal}/>, {
    alternateScreen: !snapshot, interactive: !snapshot, exitOnCtrlC: false,
    incrementalRendering: true, maxFps: 20, patchConsole: false,
  });
  const stop = (): void => instance.unmount();
  process.on('SIGTERM', stop); process.on('SIGINT', stop);
  try {
    if (snapshot) { await instance.waitUntilRenderFlush(); instance.unmount(); }
    await instance.waitUntilExit();
  } finally {
    process.off('SIGTERM', stop); process.off('SIGINT', stop);
    instance.cleanup(); await controller.close();
  }
}

try { await main(); } catch (error: unknown) {
  process.stderr.write(`启动失败：${error instanceof Error ? error.message : '未知错误'}\n`);
  process.exitCode = 1;
}
