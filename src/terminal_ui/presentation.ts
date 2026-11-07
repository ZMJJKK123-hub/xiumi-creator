import stringWidth from 'string-width'; // Terminal cell width handles CJK and emoji instead of UTF-16 lengths.
import type {DisplayRow, EditAction, EditorState, ScrollAnchor, TranscriptEntry, UiEvent, UiState} from './contracts.js'; // Pure presentation inputs and outputs.

const SEGMENTER = new Intl.Segmenter('zh', {granularity: 'grapheme'}); // Never split an emoji or combining sequence.

/** Split editable text into graphemes. Args: raw Unicode text. Returns: segments, empty for empty input.
 * Globals: SEGMENTER. Calls: Intl.Segmenter.segment. */
export function graphemes(text: string): string[] { return Array.from(SEGMENTER.segment(text), item => item.segment); }

/** Strip terminal control sequences from display/input; preserve newlines in message data.
 * Args: untrusted text. Returns: printable Unicode with tabs expanded. Globals: None. Calls: String.replace.
 * Boundary: ESC/OSC/CSI, carriage returns, C0/C1 controls never reach stdout. */
export function printable(text: string): string {
  return text.replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '')
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g, '').replace(/\t/g, '  ');
}

/** Wrap raw text at cell boundaries. Args: text, width in columns. Returns: at least one row.
 * Globals: None. Calls: printable, graphemes, stringWidth. Boundary: widths below one become one; oversized glyphs become a space. */
export function wrapText(text: string, width: number): string[] {
  const limit = Math.max(1, Math.floor(width));
  const rows: string[] = [];
  for (const paragraph of printable(text).split('\n')) {
    let line = '';
    let used = 0;
    for (const glyph of graphemes(paragraph)) {
      const size = stringWidth(glyph);
      if (used + size > limit && line) { rows.push(line); line = ''; used = 0; }
      if (size > limit) { line += ' '; used += 1; }
      else { line += glyph; used += size; }
    }
    rows.push(line);
  }
  return rows;
}

/** Cell-bounded summary without changing stored text. Args: text/width. Returns: first row plus ellipsis on overflow.
 * Globals: None. Calls: wrapText, stringWidth, graphemes. Boundary: tiny widths remain within their budget. */
export function summary(text: string, width: number): string {
  const limit = Math.max(1, width);
  const flattened = printable(text).replace(/\n/g, ' ↵ ');
  if (stringWidth(flattened) <= limit) return flattened;
  return limit === 1 ? '…' : (wrapText(flattened, limit - 1)[0] ?? '') + '…';
}

/** Empty session factory for each mounted UI; no process-global event store.
 * Args: None. Returns: fresh session. Globals: None. Calls: None. */
export function initialState(): UiState {
  return {entries: [], task: null, model: {model: '', baseUrl: '', configured: false}, loggedIn: false};
}

/** Pure event reduction. Args: previous session/event. Returns: new state or the same object for stale/duplicate events.
 * Globals: None. Calls: Array.map/filter. Boundary: completed tasks reject late events; each round/call is paired by ID. */
export function reduceEvent(state: UiState, event: UiEvent): UiState {
  if (event.type === 'notice') return {...state, entries: [...state.entries, {kind: 'message', id: event.id, taskId: null, role: 'system', text: event.text}]};
  if (event.type === 'model_changed') return {...state, model: {...event.summary}};
  if (event.type === 'login_changed') return {...state, loggedIn: event.loggedIn};
  if (event.type === 'task_started') {
    if (isBusy(state) || state.task?.id === event.taskId) return state;
    return {...state, task: {id: event.taskId, status: 'running', startedAt: event.at}, entries: [...state.entries,
      {kind: 'message', id: `${event.taskId}:user`, taskId: event.taskId, role: 'user', text: event.text}]};
  }
  if (!isBusy(state) || state.task?.id !== event.taskId) return state;
  if (event.type === 'task_finished') {
    const entries = state.entries.map((entry): TranscriptEntry => {
      if (entry.taskId !== event.taskId || entry.kind === 'message' || entry.status !== 'running') return entry;
      return entry.kind === 'thinking' ? {...entry, status: event.status, endedAt: event.at} : {...entry, status: event.status};
    });
    return {...state, task: {...state.task, status: event.status}, entries: [...entries,
      {kind: 'message', id: `${event.taskId}:done`, taskId: event.taskId, role: 'system', text: event.text}]};
  }
  if (event.type === 'message') {
    if (state.entries.some(entry => entry.id === event.id)) return state;
    return {...state, entries: [...state.entries, {kind: 'message', id: event.id, taskId: event.taskId, role: 'assistant', text: event.text}]};
  }
  if (event.type === 'tool_started' || event.type === 'thinking_started') {
    if (state.entries.some(entry => entry.id === event.id)) return state;
    const entry: TranscriptEntry = event.type === 'tool_started'
      ? {kind: 'tool', id: event.id, taskId: event.taskId, name: event.name, argumentsText: event.argumentsText, result: '', status: 'running'}
      : {kind: 'thinking', id: event.id, taskId: event.taskId, text: '', expanded: false, scrollRow: null, startedAt: event.at, endedAt: null, status: 'running'};
    return {...state, entries: [...state.entries, entry]};
  }
  return {...state, entries: state.entries.map(entry => {
    if (entry.id !== event.id || entry.kind === 'message' || entry.status !== 'running') return entry;
    switch (event.type) {
      case 'thinking_delta': return entry.kind === 'thinking' ? {...entry, text: entry.text + event.text} : entry;
      case 'thinking_finished': return entry.kind === 'thinking' ? {...entry, status: 'completed', endedAt: event.at} : entry;
      case 'tool_finished': return entry.kind === 'tool' ? {...entry, status: event.ok ? 'completed' : 'failed', result: event.result} : entry;
    }
  })};
}

/** Whether a session accepts interruption rather than a second task. Args: state. Returns: boolean. Globals/Calls: None. */
export function isBusy(state: UiState): boolean { return state.task?.status === 'running' || state.task?.status === 'cancelling'; }

/** Clear settled history while retaining active-task entries. Args: state. Returns: a new session. Globals: None. Calls: isBusy. */
export function clearHistory(state: UiState): UiState {
  return {...state, entries: isBusy(state) ? state.entries.filter(entry => entry.taskId === state.task?.id) : []};
}

/** Toggle the newest nonempty reasoning round without touching older rounds. Args: state. Returns: changed/unchanged state.
 * Globals: None. Calls: Array.findLast. Boundary: empty/no rounds are a no-op. */
export function toggleThinking(state: UiState, id?: string): UiState {
  const last = id ? state.entries.find(entry => entry.id === id && entry.kind === 'thinking') : state.entries.findLast(entry => entry.kind === 'thinking' && entry.text.length > 0);
  return last ? {...state, entries: state.entries.map(entry => entry.id === last.id && entry.kind === 'thinking' ? {...entry, expanded: !entry.expanded} : entry)} : state;
}

/** Format ordered transcript rows using current width; original text stays untouched.
 * Args: session, columns, current clock, expanded reasoning height. Returns: stable row IDs for scroll anchors.
 * Globals: None. Calls: wrapText, summary. Boundary: empty reasoning is omitted after completion. */
export function displayRows(state: UiState, width: number, now: number, thinkingLines: number): DisplayRow[] {
  const rows: DisplayRow[] = [];
  for (const entry of state.entries) {
    let text: string;
    let tone: DisplayRow['tone'] = 'normal';
    if (entry.kind === 'message') {
      const prefix = entry.role === 'user' ? '> ' : entry.role === 'assistant' ? '⏺ ' : '└ ';
      text = prefix + entry.text;
      tone = entry.role === 'system' ? 'muted' : 'normal';
    } else if (entry.kind === 'tool') {
      text = `└ ${entry.name}(${summary(entry.argumentsText, Math.max(1, width - entry.name.length - 5))})`;
      if (entry.result) text += '\n  ' + wrapText(entry.result, Math.max(1, width - 2)).slice(0, 2).join('\n  ');
      tone = entry.status === 'failed' ? 'error' : 'muted';
    } else {
      if (!entry.text && entry.status !== 'running') continue;
      const seconds = Math.max(0, Math.floor(((entry.endedAt ?? now) - entry.startedAt) / 1000));
      text = `✻ ${entry.status === 'running' ? 'thinking' : entry.status === 'cancelled' ? '已中断' : entry.status === 'failed' ? '失败' : '思考了'} ${seconds}s · Ctrl+O ${entry.expanded ? '收起' : '展开'}`;
      if (entry.expanded) {
        const thoughtRows = wrapText(entry.text, width);
        const maxStart = Math.max(0, thoughtRows.length - thinkingLines);
        const first = entry.scrollRow === null ? maxStart : Math.min(maxStart, entry.scrollRow);
        text += '\n' + thoughtRows.slice(first, first + thinkingLines).join('\n');
      }
      tone = 'accent';
    }
    for (const [index, line] of wrapText(text, width).entries()) rows.push({key: `${entry.id}:${index}`, entryId: entry.id, text: line, tone});
    rows.push({key: `${entry.id}:gap`, entryId: entry.id, text: '', tone: 'normal'});
  }
  return rows;
}

/** Resolve a reading anchor after reflow. Args: rows, anchor, height. Returns: clamped start index; null follows bottom.
 * Globals: None. Calls: Array.findIndex. Boundary: removed anchors fall back to the oldest visible content. */
export function viewportStart(rows: readonly DisplayRow[], anchor: ScrollAnchor | null, height: number): number {
  const max = Math.max(0, rows.length - height);
  if (!anchor) return max;
  const first = rows.findIndex(row => row.entryId === anchor.entryId);
  return Math.max(0, Math.min(max, (first < 0 ? 0 : first) + anchor.row));
}

/** Editing reducer with grapheme-aware selections. Args: editor/action. Returns: valid caret and text after edit.
 * Globals: None. Calls: graphemes, printable. Boundary: movement clamps; deletion at either edge is safe. */
export function editText(state: EditorState, action: EditAction): EditorState {
  const chars = graphemes(state.text);
  const from = Math.min(state.cursor, state.anchor ?? state.cursor);
  const to = Math.max(state.cursor, state.anchor ?? state.cursor);
  if (action.type === 'select_all') return {...state, cursor: chars.length, anchor: 0};
  if (action.type === 'move' || action.type === 'home' || action.type === 'end') {
    const target = action.type === 'home' ? 0 : action.type === 'end' ? chars.length : Math.max(0, Math.min(chars.length, state.cursor + action.delta));
    return {...state, cursor: target, anchor: action.select ? state.anchor ?? state.cursor : null};
  }
  let start = from;
  let end = to;
  if (from === to && action.type === 'backspace') start = Math.max(0, from - 1);
  if (from === to && action.type === 'delete') end = Math.min(chars.length, to + 1);
  const insert = action.type === 'insert' ? graphemes(printable(action.text)) : [];
  return {text: [...chars.slice(0, start), ...insert, ...chars.slice(end)].join(''), cursor: start + insert.length, anchor: null};
}
