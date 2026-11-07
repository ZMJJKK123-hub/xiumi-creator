import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises'; // Isolated test files; cleanup is confined to the generated temp directory.
import {tmpdir} from 'node:os'; // Platform temporary directory.
import {join} from 'node:path'; // Portable temporary file paths.
import {PassThrough} from 'node:stream'; // Terminal packets tested without touching real console modes.
import {afterEach, describe, expect, it, vi} from 'vitest'; // Lifecycle and boundary assertions.
import type {LoggerPort, RuntimePort, UiEvent} from '../../src/terminal_ui/contracts.js'; // Fake services implement the production contract.
import {UiController} from '../../src/terminal_ui/controller.js'; // Public orchestration API.
import {PreviewRuntime} from '../../src/terminal_ui/preview_runtime.js'; // Real preview file/cancellation implementation.
import {createTerminalPort, wheelDirections} from '../../src/terminal_ui/terminal_io.js'; // Native input adapter with injected streams.
import {DEFAULT_UI_CONFIG} from '../../src/terminal_ui/theme.js'; // Test timing overrides retain configured bounds.
import {createLogger} from '../../src/infrastructure/log.js'; // Redacted diagnostics.

const temporaryDirectories: string[] = []; // Only directories created by these tests are removed.
const logger: LoggerPort = {error: vi.fn()}; // Keeps tests independent of project-local logs.
afterEach(async () => { await Promise.all(temporaryDirectories.splice(0).map(path => rm(path, {recursive: true, force: true}))); });

/** One test-scoped directory. Args: None. Returns: generated path. Globals: temporaryDirectories. Calls: mkdtemp. */
async function temp(): Promise<string> { const path = await mkdtemp(join(tmpdir(), 'xiumi-ui-test-')); temporaryDirectories.push(path); return path; }

describe('runtime boundaries', () => {
  it('simulates two rounds and produces exactly one completion; cancellation stops remaining events', async () => {
    const runtime = new PreviewRuntime({...DEFAULT_UI_CONFIG, previewStepMs: 1});
    const events: UiEvent[] = [];
    runtime.subscribe(event => events.push(event));
    await runtime.dispatch({type: 'submit_task', text: '完整任务'});
    await vi.waitFor(() => expect(events.filter(event => event.type === 'task_finished')).toHaveLength(1));
    expect(events.filter(event => event.type === 'thinking_started')).toHaveLength(2);
    expect(events.filter(event => event.type === 'tool_finished')).toHaveLength(2);
    events.length = 0;
    await runtime.dispatch({type: 'submit_task', text: '中断'});
    const start = events.find(event => event.type === 'task_started');
    if (start?.type !== 'task_started') throw new Error('missing task start');
    await runtime.dispatch({type: 'interrupt', taskId: start.taskId});
    await vi.waitFor(() => expect(events.find(event => event.type === 'task_finished')).toMatchObject({status: 'cancelled'}));
    expect(events.filter(event => event.type === 'task_finished')).toHaveLength(1);
    await runtime.close();
  });
  it('loads full UTF-8 file contents and reports missing/directory/size/encoding/empty errors', async () => {
    const root = await temp();
    const runtime = new PreviewRuntime({...DEFAULT_UI_CONFIG, maxFileBytes: 64});
    await writeFile(join(root, 'a b.md'), '第一段\n\n第二段');
    expect(await runtime.dispatch({type: 'load_file', path: `"${join(root, 'a b.md')}"`})).toEqual({type: 'task_text', text: '第一段\n\n第二段'});
    await writeFile(join(root, 'large.md'), 'x'.repeat(65));
    await writeFile(join(root, 'invalid.md'), Buffer.from([0xff, 0xff]));
    await writeFile(join(root, 'empty.md'), '  ');
    for (const path of [root, join(root, 'missing.md'), join(root, 'large.md'), join(root, 'invalid.md'), join(root, 'empty.md'), '']) {
      expect(await runtime.dispatch({type: 'load_file', path})).toMatchObject({type: 'rejected'});
    }
    await runtime.close();
  });
  it('validates the whole model configuration before emitting a safe summary', async () => {
    const runtime = new PreviewRuntime(DEFAULT_UI_CONFIG);
    const events: UiEvent[] = [];
    runtime.subscribe(event => events.push(event));
    expect(await runtime.dispatch({type: 'save_model', model: 'model', apiKey: 'private-key', baseUrl: 'ftp://example.com'})).toMatchObject({type: 'rejected'});
    expect(events).toEqual([]);
    await runtime.dispatch({type: 'save_model', model: 'model', apiKey: 'private-key', baseUrl: 'https://example.com/v1'});
    expect(events).toHaveLength(1);
    expect(JSON.stringify(events)).not.toContain('private-key');
    expect(await runtime.dispatch({type: 'capture'})).toMatchObject({type: 'rejected', code: 'unavailable'});
    await runtime.close();
  });
  it('controller contains runtime failures, rejects empty tasks and unsubscribes on shutdown', async () => {
    const unsubscribe = vi.fn();
    const close = vi.fn(async () => undefined);
    const runtime: RuntimePort = {subscribe: () => unsubscribe, dispatch: vi.fn(async () => { throw new Error('secret payload'); }), close};
    const controller = new UiController(runtime, DEFAULT_UI_CONFIG, logger);
    expect(await controller.send({type: 'submit_task', text: ' '})).toMatchObject({type: 'rejected', code: 'invalid_input'});
    expect(runtime.dispatch).not.toHaveBeenCalled();
    expect(await controller.send({type: 'capture'})).toMatchObject({type: 'rejected', code: 'io_error'});
    await controller.close(); await controller.close();
    expect(unsubscribe).toHaveBeenCalledOnce(); expect(close).toHaveBeenCalledOnce();
    controller.receive({type: 'notice', id: 'late', text: 'late'});
    expect(controller.store.read().entries).toEqual([]);
  });
  it('logs structured context without secret error messages', async () => {
    const root = await temp();
    createLogger(root, 'test-trace').error('model.save', new Error('private-key\nprivate-key-second-line'));
    const log = await readFile(join(root, 'terminal-ui.log'), 'utf8');
    expect(log).toContain('test-trace'); expect(log).toContain('model.save'); expect(log).not.toContain('private-key');
  });
  it('retains a reasoning reading position as new tokens arrive and contains logger failures', async () => {
    const runtime: RuntimePort = {subscribe: () => () => undefined, dispatch: async () => { throw new Error('runtime failure'); }, close: async () => undefined};
    const controller = new UiController(runtime, {...DEFAULT_UI_CONFIG, thinkingLines: 2}, {error: () => { throw new Error('disk failure'); }});
    controller.receive({type: 'task_started', taskId: 'a', text: '任务', at: 0});
    controller.receive({type: 'thinking_started', taskId: 'a', id: 'r', at: 0});
    controller.receive({type: 'thinking_delta', taskId: 'a', id: 'r', text: '一\n二\n三\n四'});
    controller.toggleThinking('r'); controller.scrollThinking('r', 1, 80);
    expect(controller.store.read().entries.find(entry => entry.id === 'r')).toMatchObject({scrollRow: 1});
    controller.receive({type: 'thinking_delta', taskId: 'a', id: 'r', text: '\n五\n六'});
    expect(controller.store.read().entries.find(entry => entry.id === 'r')).toMatchObject({scrollRow: 1});
    expect(await controller.send({type: 'capture'})).toMatchObject({type: 'rejected', message: expect.stringContaining('日志无法写入')});
    await controller.close();
  });
});

describe('terminal packets and cleanup', () => {
  it('parses wheel directions and ignores ordinary clicks', () => {
    expect(wheelDirections('\x1b[<64;10;10M\x1b[<65;10;10M\x1b[<0;1;1M')).toEqual([-1, 1]);
  });
  it('buffers split packets and removes subscriptions/mouse modes on teardown', () => {
    const input = new PassThrough(); const output = new PassThrough();
    let modes = '';
    output.on('data', (chunk: Buffer) => { modes += String(chunk); });
    const wheel = vi.fn();
    const stop = createTerminalPort(input, output, DEFAULT_UI_CONFIG).subscribeWheel(wheel);
    input.write('\x1b[<6'); input.write('4;1;1M');
    expect(wheel).toHaveBeenCalledWith(-1);
    stop();
    expect(input.listenerCount('data')).toBe(0);
    expect(modes).toContain('\x1b[?1000l'); expect(modes).toContain('\x1b[?1006l');
    input.end(); output.end();
  });
});
