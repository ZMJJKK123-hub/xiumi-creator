import {mkdtemp, rm, writeFile} from 'node:fs/promises'; // Task-file interaction uses an isolated directory.
import {tmpdir} from 'node:os'; // Host temporary directory.
import {join} from 'node:path'; // Cross-platform test paths.
import {setTimeout as pause} from 'node:timers/promises'; // Allow React and Ink to finish actual render commits.
import {cleanup, render} from 'ink-testing-library'; // Official Ink input/output harness.
import stringWidth from 'string-width'; // Verify cell-aligned viewport bounds.
import {afterEach, describe, expect, it, vi} from 'vitest'; // Interactive assertions rather than static implementation snapshots.
import type {TerminalPort} from '../../src/terminal_ui/contracts.js'; // Fake platform boundary without real clipboard access.
import {TerminalApp} from '../../src/terminal_ui/app.js'; // Real rendering root.
import {UiController} from '../../src/terminal_ui/controller.js'; // Real event/session orchestration.
import {PreviewRuntime} from '../../src/terminal_ui/preview_runtime.js'; // Offline runtime validates production event shapes.
import {DEFAULT_UI_CONFIG} from '../../src/terminal_ui/theme.js'; // Consistent component policies.

const controllers: UiController[] = []; // Test-owned runtime lifecycles.
const directories: string[] = []; // Test-owned temporary directories.
afterEach(async () => { cleanup(); await Promise.all(controllers.splice(0).map(controller => controller.close())); await Promise.all(directories.splice(0).map(path => rm(path, {recursive: true, force: true}))); });

/** Mount an isolated renderer. Args: optional columns/rows. Returns: input/output handles and controller. No real terminal or configuration I/O. */
function mount(columns = 80, rows = 24) {
  const config = {...DEFAULT_UI_CONFIG, frameMs: 5, previewStepMs: 20};
  const controller = new UiController(new PreviewRuntime(config), config, {error: vi.fn()});
  controllers.push(controller);
  const stopWheel = vi.fn();
  const terminal: TerminalPort = {readClipboard: vi.fn(async () => '剪贴板正文'), subscribeWheel: vi.fn(() => stopWheel)};
  const view = render(<TerminalApp controller={controller} terminal={terminal} dimensions={{columns, rows}}/>);
  return {...view, controller, terminal, stopWheel};
}

/** Type a packet and wait for a committed render. Args: harness/packet. Returns: void promise. */
async function press(view: ReturnType<typeof mount>, packet: string): Promise<void> { view.stdin.write(packet); await pause(35); }

describe('terminal UI', () => {
  it.each([[80, 24], [110, 32], [160, 50], [40, 12], [20, 6]])('keeps layout within %ix%i', async (columns, rows) => {
    const view = mount(columns, rows);
    await pause(40);
    const frame = view.lastFrame() ?? '';
    expect(frame).toContain('渲染预览');
    expect(frame.split('\n').length).toBeLessThanOrEqual(rows);
    expect(frame.split('\n').every(line => stringWidth(line) <= columns)).toBe(true);
    await press(view, '中文输入🙂');
    expect(view.lastFrame()).toContain('中文输入🙂');
  });
  it('submits raw pasted task once and preserves both reasoning rounds', async () => {
    const view = mount(); await pause(40);
    await press(view, '\x1b[200~第一段\n第二段\x1b[201~');
    await press(view, '\r');
    await vi.waitFor(() => expect(view.controller.store.read().task?.status).toBe('completed'));
    const entries = view.controller.store.read().entries;
    expect(entries.filter(entry => entry.kind === 'message' && entry.role === 'user')).toHaveLength(1);
    expect(entries.find(entry => entry.kind === 'message' && entry.role === 'user')).toMatchObject({text: '第一段\n第二段'});
    expect(entries.filter(entry => entry.kind === 'thinking')).toHaveLength(2);
    await press(view, '\x0f');
    expect(view.lastFrame()).toContain('这是可回放');
  });
  it('completes /file but preserves an argument including spaces and submits the actual file text', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'xiumi-ui-app-')); directories.push(directory);
    const path = join(directory, 'a b.md'); await writeFile(path, '文件中的完整正文\n第二段');
    const view = mount(); await pause(40);
    await press(view, '/f'); await press(view, '\r');
    await press(view, `"${path}"`); await press(view, '\r');
    await vi.waitFor(() => expect(view.controller.store.read().task?.status).toBe('completed'));
    expect(view.controller.store.read().entries.find(entry => entry.kind === 'message' && entry.role === 'user')).toMatchObject({text: '文件中的完整正文\n第二段'});
  });
  it('isolates modal input, rejects an invalid URL, masks secrets and updates summary only after successful save', async () => {
    const view = mount(); await pause(40);
    await press(view, '/model'); await press(view, '\r');
    await press(view, 'demo-model'); await press(view, '\r');
    await press(view, 'private-key'); await press(view, '\r');
    await press(view, 'invalid'); await press(view, '\r');
    expect(view.lastFrame()).toContain('请输入完整接口地址');
    expect(view.controller.store.read().model.model).toBe('');
    expect(view.frames.join('\n')).not.toContain('private-key');
    expect(view.controller.store.read().entries).toHaveLength(0);
    await press(view, '\x01'); await press(view, 'https://example.com/v1'); await press(view, '\r');
    await vi.waitFor(() => expect(view.controller.store.read().model.model).toBe('demo-model'));
    expect(view.lastFrame()).not.toContain('模型配置 ·');
    expect(JSON.stringify(view.controller.store.read())).not.toContain('private-key');
  });
  it('clear during reasoning keeps the task alive; escape produces one cancellation', async () => {
    const view = mount(); await pause(40);
    await press(view, '需要中断的任务'); await press(view, '\r'); await press(view, '\x0c'); await press(view, '\x1b');
    await vi.waitFor(() => expect(view.controller.store.read().task?.status).toBe('cancelled'));
    expect(view.controller.store.read().entries.filter(entry => entry.kind === 'message' && entry.text === '⏹ 已中断')).toHaveLength(1);
    expect(view.controller.store.read().entries.some(entry => entry.kind === 'message' && entry.role === 'user')).toBe(true);
  });
  it('resizes from stored text and keeps reading history until End is pressed', async () => {
    const view = mount(); await pause(40);
    for (let i = 0; i < 50; i++) view.controller.notice(`历史 ${i} ${'中文'.repeat(25)}`);
    view.controller.store.flush(); await pause(40);
    await press(view, '\x1b[5~');
    expect(view.lastFrame()).toContain('历史阅读');
    const before = view.lastFrame();
    view.controller.notice('新消息不应拉回底部'); view.controller.store.flush(); await pause(40);
    expect(view.lastFrame()).toBe(before);
    view.rerender(<TerminalApp controller={view.controller} terminal={view.terminal} dimensions={{columns: 110, rows: 32}}/>); await pause(40);
    expect(view.lastFrame()).toContain('历史阅读');
    await press(view, '\x1b[F');
    expect(view.lastFrame()).toContain('新消息不应拉回底部');
    expect(view.lastFrame()).not.toContain('历史阅读');
    view.unmount(); expect(view.stopWheel).toHaveBeenCalledOnce();
  });
  it('reads the system clipboard through one adapter and does not run /login as a task', async () => {
    const view = mount(); await pause(40);
    await press(view, '\x16');
    expect(view.lastFrame()).toContain('剪贴板正文');
    expect(view.terminal.readClipboard).toHaveBeenCalledOnce();
    await press(view, '\x01'); await press(view, '/login'); await press(view, '\r');
    expect(view.controller.store.read().loggedIn).toBe(true);
    expect(view.controller.store.read().task).toBeNull();
  });
  it('keeps selected completion visible in a short terminal and renders compact modal focus', async () => {
    const view = mount(40, 12); await pause(40);
    await press(view, '/');
    for (let i = 0; i < 4; i++) await press(view, '\t');
    expect(view.lastFrame()).toContain('› /help');
    await press(view, '\x01'); await press(view, '/model'); await press(view, '\r');
    view.rerender(<TerminalApp controller={view.controller} terminal={view.terminal} dimensions={{columns: 20, rows: 6}}/>); await pause(40);
    expect(view.lastFrame()).toContain('配置 模型');
    await press(view, '\t');
    expect(view.lastFrame()).toContain('配置 密钥');
    await press(view, 'secret');
    expect(view.lastFrame()).not.toContain('secret');
    await press(view, '\x1b');
    expect(view.lastFrame()).toContain('渲染预览');
  });
});
