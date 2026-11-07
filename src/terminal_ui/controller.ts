import {randomUUID} from 'node:crypto'; // Stable UI notice identifiers; no credentials or task text are logged.
import type {IntentResult, LoggerPort, RuntimePort, UiConfig, UiEvent, UiIntent} from './contracts.js'; // Runtime/UI boundary contracts.
import {clearHistory, isBusy, reduceEvent, toggleThinking, wrapText} from './presentation.js'; // Pure state transformations.
import {SessionStore} from './session_store.js'; // Session-local storage with batched rendering.

/** Controller connects a runtime to one UI. Attributes: store/runtime/subscription/disposed.
 * Lifecycle: constructor subscribes -> send/user actions -> close unsubscribes before runtime shutdown. */
export class UiController {
  readonly store: SessionStore; // Rendering snapshot store, isolated from runtime and component lifecycles.
  private readonly unsubscribe: () => void; // Removed before shutdown so late completions cannot repaint.
  private disposed = false; // All public entry points become inert after close.
  constructor(private readonly runtime: RuntimePort, readonly config: UiConfig, private readonly logger: LoggerPort) {
    this.store = new SessionStore(config);
    this.unsubscribe = runtime.subscribe(event => this.receive(event));
  }
  /** Consume backend events. Args: typed event. Returns: void. Globals: None. Calls: reduceEvent/store.update.
   * Boundary: closed sessions ignore all events; task terminal states flush the final frame immediately. */
  receive(event: UiEvent): void {
    if (this.disposed) return;
    this.store.update(reduceEvent(this.store.read(), event), event.type === 'task_finished');
  }
  /** Show a local status without coupling callers to components. Args: text. Returns: void. Globals: None. Calls: receive/randomUUID. */
  notice(text: string): void { this.receive({type: 'notice', id: randomUUID(), text}); }
  /** Send a validated intent. Args: intent. Returns: acceptance, file content or a user-visible rejection.
   * Globals: None. Calls: runtime.dispatch/logger.error. Boundary: empty/oversized tasks, busy sessions and closed controllers are rejected; exceptions never escape input handlers. */
  async send(intent: UiIntent): Promise<IntentResult> {
    if (this.disposed) return {type: 'rejected', code: 'unavailable', message: '界面已关闭'};
    if (intent.type === 'submit_task' && (!intent.text.trim() || intent.text.length > this.config.maxTaskChars)) {
      return {type: 'rejected', code: 'invalid_input', message: `任务不能为空，且不能超过 ${this.config.maxTaskChars} 字符`};
    }
    if ((intent.type === 'submit_task' || intent.type === 'login' || intent.type === 'save_model') && isBusy(this.store.read())) {
      return {type: 'rejected', code: 'busy', message: '任务进行中，Esc 中断后重试'};
    }
    try { return await this.runtime.dispatch(intent); }
    catch (error: unknown) {
      try { this.logger.error(`runtime.${intent.type}`, error); }
      catch { return {type: 'rejected', code: 'io_error', message: '运行服务调用失败，且日志无法写入，请检查日志目录权限'}; }
      return {type: 'rejected', code: 'io_error', message: '运行服务调用失败，请查看日志后重试'};
    }
  }
  /** Clear only settled history. Args: None. Returns: void. Globals: None. Calls: clearHistory/store.update. */
  clear(): void { this.store.update(clearHistory(this.store.read()), true); }
  /** Toggle latest nonempty thought. Args: None. Returns: void. Globals: None. Calls: toggleThinking/store.update. */
  toggleThinking(id?: string): void { this.store.update(toggleThinking(this.store.read(), id), true); }
  /** Scroll one expanded round independently. Args: round ID, row delta, content width. Returns: void.
   * Globals: None. Calls: wrapText/store.update; bounds clamp and unrelated entries stay unchanged. */
  scrollThinking(id: string, delta: number, width: number): void {
    const state = this.store.read();
    this.store.update({...state, entries: state.entries.map(entry => {
      if (entry.kind !== 'thinking' || entry.id !== id || !entry.expanded) return entry;
      const max = Math.max(0, wrapText(entry.text, width).length - this.config.thinkingLines);
      const first = Math.max(0, Math.min(max, (entry.scrollRow ?? max) - delta));
      return {...entry, scrollRow: first >= max ? null : first};
    })}, true);
  }
  /** Cancel only the current task and keep UI busy until its terminal event arrives.
   * Args: None. Returns: void promise. Globals: None. Calls: send/store.update/notice; idle is a no-op. */
  async interrupt(): Promise<void> {
    const state = this.store.read();
    if (!state.task || !isBusy(state) || state.task.status === 'cancelling') return;
    const taskId = state.task.id;
    this.store.update({...state, task: {...state.task, status: 'cancelling'}}, true);
    const result = await this.send({type: 'interrupt', taskId});
    if (result.type === 'rejected') {
      const current = this.store.read();
      if (current.task?.id === taskId && current.task.status === 'cancelling') this.store.update({...current, task: {...current.task, status: 'running'}}, true);
      this.notice(result.message);
    }
  }
  /** Release subscriptions and timers before closing the runtime. Args: None. Returns: void promise.
   * Globals: None. Calls: unsubscribe/store.dispose/runtime.close/logger; idempotent, shutdown errors logged without escaping. */
  async close(): Promise<void> {
    if (this.disposed) return;
    this.disposed = true;
    this.unsubscribe(); this.store.dispose();
    try { await this.runtime.close(); } catch (error: unknown) { this.logger.error('runtime.close', error); }
  }
}
