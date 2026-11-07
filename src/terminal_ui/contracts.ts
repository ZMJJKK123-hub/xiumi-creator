/** UI boundary contracts. Backend adapters depend on this protocol, never on React components. */
export type TaskStatus = 'running' | 'cancelling' | 'completed' | 'cancelled' | 'failed';
export type Completion = 'completed' | 'cancelled' | 'failed';
export type Role = 'user' | 'assistant' | 'system';
export interface ModelSummary { readonly model: string; readonly baseUrl: string; readonly configured: boolean }
export interface Task { readonly id: string; readonly status: TaskStatus; readonly startedAt: number }
export interface MessageEntry {
  readonly kind: 'message'; readonly id: string; readonly taskId: string | null;
  readonly role: Role; readonly text: string;
}
export interface ToolEntry {
  readonly kind: 'tool'; readonly id: string; readonly taskId: string;
  readonly name: string; readonly argumentsText: string; readonly result: string;
  readonly status: 'running' | Completion;
}
export interface ThinkingEntry {
  readonly kind: 'thinking'; readonly id: string; readonly taskId: string;
  readonly text: string; readonly expanded: boolean; readonly scrollRow: number | null; readonly startedAt: number;
  readonly endedAt: number | null; readonly status: 'running' | Completion;
}
export type TranscriptEntry = MessageEntry | ToolEntry | ThinkingEntry;
export interface UiState {
  readonly entries: readonly TranscriptEntry[];
  readonly task: Task | null;
  readonly model: ModelSummary;
  readonly loggedIn: boolean;
}
/** Every task-scoped event carries its task ID; tools and rounds additionally use a stable ID. */
export type UiEvent =
  | {readonly type: 'task_started'; readonly taskId: string; readonly text: string; readonly at: number}
  | {readonly type: 'task_finished'; readonly taskId: string; readonly status: Completion; readonly text: string; readonly at: number}
  | {readonly type: 'message'; readonly taskId: string; readonly id: string; readonly text: string}
  | {readonly type: 'tool_started'; readonly taskId: string; readonly id: string; readonly name: string; readonly argumentsText: string}
  | {readonly type: 'tool_finished'; readonly taskId: string; readonly id: string; readonly result: string; readonly ok: boolean}
  | {readonly type: 'thinking_started'; readonly taskId: string; readonly id: string; readonly at: number}
  | {readonly type: 'thinking_delta'; readonly taskId: string; readonly id: string; readonly text: string}
  | {readonly type: 'thinking_finished'; readonly taskId: string; readonly id: string; readonly at: number}
  | {readonly type: 'notice'; readonly id: string; readonly text: string}
  | {readonly type: 'model_changed'; readonly summary: ModelSummary}
  | {readonly type: 'login_changed'; readonly loggedIn: boolean};
/** Credentials are transient command payloads and are never copied into UiState or transcript events. */
export type UiIntent =
  | {readonly type: 'submit_task'; readonly text: string}
  | {readonly type: 'interrupt'; readonly taskId: string}
  | {readonly type: 'load_file'; readonly path: string}
  | {readonly type: 'save_model'; readonly model: string; readonly apiKey: string; readonly baseUrl: string}
  | {readonly type: 'login'}
  | {readonly type: 'capture'};
export type IntentResult =
  | {readonly type: 'accepted'}
  | {readonly type: 'task_text'; readonly text: string}
  | {readonly type: 'rejected'; readonly code: 'invalid_input' | 'busy' | 'unavailable' | 'io_error'; readonly message: string};
export interface RuntimePort {
  subscribe(listener: (event: UiEvent) => void): () => void;
  dispatch(intent: UiIntent): Promise<IntentResult>;
  close(): Promise<void>;
}
export interface UiConfig {
  readonly frameMs: number; readonly previewStepMs: number; readonly clipboardTimeoutMs: number;
  readonly maxTaskChars: number; readonly maxFileBytes: number; readonly thinkingLines: number;
}
export interface LoggerPort { error(operation: string, error: unknown): void }
export interface TerminalPort {
  readClipboard(): Promise<string>;
  subscribeWheel(listener: (direction: -1 | 1) => void): () => void;
}
export interface EditorState { readonly text: string; readonly cursor: number; readonly anchor: number | null }
export type EditAction =
  | {readonly type: 'insert'; readonly text: string}
  | {readonly type: 'move'; readonly delta: number; readonly select: boolean}
  | {readonly type: 'home'; readonly select: boolean}
  | {readonly type: 'end'; readonly select: boolean}
  | {readonly type: 'backspace' | 'delete' | 'select_all'};
export interface DisplayRow { readonly key: string; readonly entryId: string; readonly text: string; readonly tone: 'normal' | 'muted' | 'accent' | 'error' }
export interface ScrollAnchor { readonly entryId: string; readonly row: number }
export type ModalState = {readonly type: 'none'} | {readonly type: 'help'} | {readonly type: 'model'};
