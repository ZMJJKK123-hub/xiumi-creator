import {afterEach, describe, expect, it, vi} from 'vitest'; // Assertions/fake clocks validate data behavior independently of the terminal.
import stringWidth from 'string-width'; // Verify actual cell budgets, including CJK/emoji.
import type {EditorState, UiEvent, UiState} from '../../src/terminal_ui/contracts.js'; // Strongly typed protocol fixtures.
import {clearHistory, displayRows, editText, graphemes, initialState, printable, reduceEvent, summary, toggleThinking, viewportStart, wrapText} from '../../src/terminal_ui/presentation.js'; // Framework-independent rendering logic.
import {SessionStore, TranscriptCache} from '../../src/terminal_ui/session_store.js'; // Frame batching and history projection reuse.
import {suggestions} from '../../src/terminal_ui/command_catalog.js'; // Command completion must preserve arguments.
import {DEFAULT_UI_CONFIG} from '../../src/terminal_ui/theme.js'; // Production defaults with test overrides.

/** Reduce a deterministic task script. Args: events. Returns: session. No external I/O. */
function run(events: readonly UiEvent[]): UiState { return events.reduce(reduceEvent, initialState()); }
const START: UiEvent = {type: 'task_started', taskId: 'a', text: '中文任务🙂', at: 1000}; // Shared lifecycle start.

afterEach(() => vi.useRealTimers());
describe('session lifecycle', () => {
  it('rejects stale tasks, duplicate messages/calls, and post-completion tokens', () => {
    const state = run([START, {type: 'thinking_started', taskId: 'a', id: 'r1', at: 1000}, {type: 'thinking_delta', taskId: 'a', id: 'r1', text: '正文'},
      {type: 'message', taskId: 'old', id: 'late', text: '不应出现'}, {type: 'message', taskId: 'a', id: 'm1', text: '完成'}, {type: 'message', taskId: 'a', id: 'm1', text: '重复'},
      {type: 'task_finished', taskId: 'a', status: 'completed', text: '完成', at: 2000}]);
    expect(state.entries.map(entry => entry.id)).toEqual(['a:user', 'r1', 'm1', 'a:done']);
    expect(reduceEvent(state, {type: 'thinking_delta', taskId: 'a', id: 'r1', text: '迟到'})).toBe(state);
    expect(reduceEvent(state, START)).toBe(state);
  });
  it('preserves separate rounds, including an empty first round', () => {
    const state = run([START, {type: 'thinking_started', taskId: 'a', id: 'r1', at: 1000}, {type: 'thinking_finished', taskId: 'a', id: 'r1', at: 1100},
      {type: 'thinking_started', taskId: 'a', id: 'r2', at: 1200}, {type: 'thinking_delta', taskId: 'a', id: 'r2', text: '第二轮依然可见'}]);
    expect(state.entries.filter(entry => entry.kind === 'thinking')).toHaveLength(2);
    expect(displayRows(toggleThinking(state), 80, 2000, 5).map(row => row.text).join('\n')).toContain('第二轮依然可见');
    expect(displayRows(state, 80, 2000, 5).filter(row => row.entryId === 'r1')).toHaveLength(0);
  });
  it.each(['cancelled', 'failed'] as const)('settles active reasoning/tools on %s exactly once', status => {
    const state = run([START, {type: 'thinking_started', taskId: 'a', id: 'r', at: 1000}, {type: 'tool_started', taskId: 'a', id: 't', name: 'test', argumentsText: ''},
      {type: 'task_finished', taskId: 'a', status, text: status, at: 2000}]);
    expect(state.entries.filter(entry => entry.kind !== 'message').every(entry => entry.status === status)).toBe(true);
    expect(reduceEvent(state, {type: 'task_finished', taskId: 'a', status, text: '重复', at: 3000})).toBe(state);
  });
  it('clear keeps an active round alive and removes settled history', () => {
    const old = run([START, {type: 'task_finished', taskId: 'a', status: 'completed', text: 'done', at: 2000}, {type: 'task_started', taskId: 'b', text: '新任务', at: 3000},
      {type: 'thinking_started', taskId: 'b', id: 'r', at: 3000}]);
    const cleared = clearHistory(old);
    expect(cleared.entries.every(entry => entry.taskId === 'b')).toBe(true);
    const continued = reduceEvent(cleared, {type: 'thinking_delta', taskId: 'b', id: 'r', text: '清屏后继续'});
    expect(displayRows(toggleThinking(continued), 80, 4000, 5).map(row => row.text).join('\n')).toContain('清屏后继续');
    expect(clearHistory(reduceEvent(continued, {type: 'task_finished', taskId: 'b', status: 'completed', text: '', at: 4000})).entries).toEqual([]);
  });
});

describe('Unicode, input and layout', () => {
  it.each([1, 2, 3, 8, 20, 80])('never exceeds %i cells or splits emoji graphemes', width => {
    const text = '中文 👩‍💻 é 🙂 完整消息';
    expect(wrapText(text, width).every(row => stringWidth(row) <= width)).toBe(true);
    expect(stringWidth(summary(text, width))).toBeLessThanOrEqual(width);
    expect(summary(text, width)).not.toMatch(/[\uD800-\uDBFF]$/);
  });
  it('reflows original content after resize, retaining full source text', () => {
    const state = run([START, {type: 'message', taskId: 'a', id: 'm', text: '完整原文'.repeat(40)}]);
    const narrow = displayRows(state, 20, 1000, 5);
    const wide = displayRows(state, 80, 1000, 5);
    expect(narrow.length).toBeGreaterThan(wide.length);
    expect(wide.map(row => row.text).join('')).toContain('完整原文'.repeat(40));
    const anchor = {entryId: 'm', row: 1};
    expect(narrow[viewportStart(narrow, anchor, 3)]?.entryId).toBe('m');
    expect(wide[viewportStart(wide, anchor, 3)]?.entryId).toBe('m');
  });
  it('edits graphemes and replaces selections without partial surrogate pairs', () => {
    let editor: EditorState = {text: '中👩‍💻é', cursor: 3, anchor: null};
    editor = editText(editor, {type: 'backspace'});
    expect(editor.text).toBe('中👩‍💻');
    editor = editText(editor, {type: 'move', delta: -1, select: true});
    editor = editText(editor, {type: 'insert', text: '替换'});
    expect(editor.text).toBe('中替换');
    editor = editText(editor, {type: 'select_all'});
    expect(editText(editor, {type: 'insert', text: '新\n正文'}).text).toBe('新\n正文');
    expect(editText({text: '', cursor: 0, anchor: null}, {type: 'delete'}).text).toBe('');
    expect(graphemes('👩‍💻é')).toHaveLength(2);
  });
  it('sanitizes executable terminal escapes without losing message newlines', () => {
    expect(printable('\x1b[31m正文\x1b]52;c;secret\x07\n下一行')).toBe('正文\n下一行');
  });
  it('completion stops after command token and never consumes /file arguments', () => {
    expect(suggestions('/')).toHaveLength(5);
    expect(suggestions('/f').map(item => item.name)).toEqual(['/file']);
    expect(suggestions('/file ')).toEqual([]);
    expect(suggestions('/file "a b.md"')).toEqual([]);
    expect(suggestions('任务')).toEqual([]);
  });
});

describe('frame scheduling', () => {
  it('reuses history rows while invalidating changed messages, thinking clocks and terminal width', () => {
    const cache = new TranscriptCache();
    const state = run([START, {type: 'thinking_started', taskId: 'a', id: 'r', at: 1000}]);
    const first = cache.project(state, 80, 1000, 5);
    const second = cache.project(state, 80, 2000, 5);
    expect(first[0]).toBe(second[0]);
    expect(second).toEqual(displayRows(state, 80, 2000, 5));
    expect(cache.project(state, 20, 3000, 5)).toEqual(displayRows(state, 20, 3000, 5));
    const updated = reduceEvent(state, {type: 'thinking_delta', taskId: 'a', id: 'r', text: '新增思考'});
    expect(cache.project(updated, 20, 3000, 5)).toEqual(displayRows(updated, 20, 3000, 5));
    const empty = clearHistory(reduceEvent(updated, {type: 'task_finished', taskId: 'a', status: 'completed', text: '', at: 4000}));
    expect(cache.project(empty, 20, 4000, 5)).toEqual([]);
  });
  it('coalesces token frames, flushes terminal state and cancels callbacks on disposal', () => {
    vi.useFakeTimers();
    const store = new SessionStore(DEFAULT_UI_CONFIG);
    const listener = vi.fn();
    store.subscribe(listener);
    store.update(reduceEvent(store.read(), START));
    store.update(reduceEvent(store.read(), {type: 'thinking_started', taskId: 'a', id: 'r', at: 1000}));
    for (let i = 0; i < 100; i++) store.update(reduceEvent(store.read(), {type: 'thinking_delta', taskId: 'a', id: 'r', text: '字'}));
    expect(listener).not.toHaveBeenCalled();
    vi.advanceTimersByTime(50);
    expect(listener).toHaveBeenCalledTimes(1);
    store.update(reduceEvent(store.read(), {type: 'task_finished', taskId: 'a', status: 'completed', text: 'done', at: 2000}), true);
    expect(listener).toHaveBeenCalledTimes(2);
    store.update({...store.read(), loggedIn: true});
    store.dispose(); vi.advanceTimersByTime(100);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});
