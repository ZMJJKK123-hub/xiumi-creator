import {randomUUID} from 'node:crypto'; // Task/call/round IDs for deterministic event correlation.
import {open} from 'node:fs/promises'; // Bounded local task-file reading; no application configuration is touched.
import {setTimeout as delay} from 'node:timers/promises'; // Abortable preview steps for cancellation verification.
import type {IntentResult, RuntimePort, UiConfig, UiEvent, UiIntent} from './contracts.js'; // Same protocol a future TS backend must implement.

/** Offline rendering runtime. Attributes: listeners, active task/abort controller, pending execution, closed flag.
 * Lifecycle: subscribe -> dispatch simulation events -> close cancels and awaits execution. No network, browser or persistent credentials. */
export class PreviewRuntime implements RuntimePort {
  private readonly listeners = new Set<(event: UiEvent) => void>(); // Session-local consumers.
  private active: {id: string; abort: AbortController} | null = null; // Exactly one task can produce events.
  private execution: Promise<void> | null = null; // Awaited during shutdown to prevent dangling work.
  private closed = false; // Stops event delivery and rejects new intents.
  constructor(private readonly config: UiConfig) {}
  /** Subscribe to preview events. Args: listener. Returns: unsubscribe closure. Globals: None. Calls: Set.add/delete. */
  subscribe(listener: (event: UiEvent) => void): () => void { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  /** Deliver only while open. Args: event. Returns: void. Listener failures are isolated by the controller boundary. */
  private emit(event: UiEvent): void { if (!this.closed) for (const listener of this.listeners) listener(event); }
  /** Accept a UI intent. Args: typed intent. Returns: typed result. Globals: None. Calls: run/readFile/emit.
   * Boundary: preview login is labelled simulated; screenshots unavailable; model values only update a safe in-memory summary. */
  async dispatch(intent: UiIntent): Promise<IntentResult> {
    if (this.closed) return {type: 'rejected', code: 'unavailable', message: '预览已关闭'};
    switch (intent.type) {
      case 'submit_task': {
        if (this.active) return {type: 'rejected', code: 'busy', message: '上一轮尚未结束'};
        if (!intent.text.trim() || intent.text.length > this.config.maxTaskChars) return {type: 'rejected', code: 'invalid_input', message: '任务为空或过长'};
        const id = randomUUID();
        const abort = new AbortController();
        this.active = {id, abort};
        this.emit({type: 'task_started', taskId: id, text: intent.text, at: Date.now()});
        this.execution = this.run(id, intent.text, abort.signal);
        return {type: 'accepted'};
      }
      case 'interrupt':
        if (this.active?.id === intent.taskId) this.active.abort.abort();
        return {type: 'accepted'};
      case 'load_file': return this.readTaskFile(intent.path);
      case 'save_model': {
        if (!intent.model.trim()) return {type: 'rejected', code: 'invalid_input', message: '请填写模型名称'};
        let url: URL;
        try { url = new URL(intent.baseUrl); } catch { return {type: 'rejected', code: 'invalid_input', message: '请输入完整接口地址'}; }
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return {type: 'rejected', code: 'invalid_input', message: '地址须为 HTTP(S)，且不能包含账号密码'};
        this.emit({type: 'model_changed', summary: {model: intent.model.trim(), baseUrl: url.toString(), configured: Boolean(intent.apiKey.trim())}});
        return {type: 'accepted'};
      }
      case 'login': this.emit({type: 'login_changed', loggedIn: true}); this.emit({type: 'notice', id: randomUUID(), text: '预览：模拟登录成功，未打开真实浏览器'}); return {type: 'accepted'};
      case 'capture': return {type: 'rejected', code: 'unavailable', message: '渲染预览未连接浏览器，无法生成页面截图'};
    }
  }
  /** Read a bounded UTF-8 task file. Args: user path. Returns: text/rejection; directories, invalid UTF-8 and oversized files are rejected. */
  private async readTaskFile(path: string): Promise<IntentResult> {
    if (!path.trim()) return {type: 'rejected', code: 'invalid_input', message: '用法：/file 路径/到/task.md'};
    try {
      const handle = await open(path.trim().replace(/^(["'])(.*)\1$/, '$2'), 'r');
      try {
        const stats = await handle.stat();
        if (!stats.isFile() || stats.size > this.config.maxFileBytes) return {type: 'rejected', code: 'invalid_input', message: `请选择大小不超过 ${this.config.maxFileBytes} 字节的任务文件`};
        const buffer = Buffer.alloc(this.config.maxFileBytes + 1);
        let total = 0;
        while (total < buffer.length) {
          const {bytesRead} = await handle.read(buffer, total, buffer.length - total, total);
          if (bytesRead === 0) break;
          total += bytesRead;
        }
        if (total > this.config.maxFileBytes) return {type: 'rejected', code: 'invalid_input', message: '任务文件过大'};
        const text = new TextDecoder('utf-8', {fatal: true}).decode(buffer.subarray(0, total));
        return text.trim() && text.length <= this.config.maxTaskChars ? {type: 'task_text', text} : {type: 'rejected', code: 'invalid_input', message: '任务文件为空或正文过长'};
      } finally { await handle.close(); }
    } catch { return {type: 'rejected', code: 'io_error', message: '读取失败：请确认文件存在、可读且使用 UTF-8 编码'}; }
  }
  /** Replay two reasoning/tool rounds. Args: task identity/text/cancellation signal. Returns: void promise.
   * Completion always settles once; aborts are cancelled, other failures are labelled failed. */
  private async run(taskId: string, text: string, signal: AbortSignal): Promise<void> {
    let status: 'completed' | 'cancelled' | 'failed' = 'completed';
    try {
      for (const round of [1, 2]) {
        const id = `${taskId}:round:${round}`;
        this.emit({type: 'thinking_started', taskId, id, at: Date.now()});
        for (const chunk of ['正在分析任务与段落结构。', '准备检查排版、图片位置和保存状态。', '这是可回放的模拟事件，用于验证终端渲染。']) {
          await delay(this.config.previewStepMs, undefined, {signal});
          this.emit({type: 'thinking_delta', taskId, id, text: chunk});
        }
        this.emit({type: 'thinking_finished', taskId, id, at: Date.now()});
        const callId = `${taskId}:tool:${round}`;
        this.emit({type: 'tool_started', taskId, id: callId, name: round === 1 ? 'preview_outline' : 'preview_layout', argumentsText: '模拟数据'});
        await delay(this.config.previewStepMs * 2, undefined, {signal});
        this.emit({type: 'tool_finished', taskId, id: callId, result: '模拟完成；未访问秀米或保存真实草稿', ok: true});
      }
      this.emit({type: 'message', taskId, id: `${taskId}:reply`, text: `界面预览完成。\n\n任务原文：\n${text}\n\n消息、两轮思考及工具结果已按顺序显示。真实排版功能将在接入 TS 后端后提供。`});
    } catch { status = signal.aborted ? 'cancelled' : 'failed'; }
    finally {
      this.active = null;
      this.emit({type: 'task_finished', taskId, status, text: status === 'cancelled' ? '⏹ 已中断' : status === 'failed' ? '⚠ 模拟任务失败' : '✻ 模拟任务完成', at: Date.now()});
    }
  }
  /** Shutdown stops delivery and waits for cancellation. Args: None. Returns: void promise. Globals: None. Calls: abort/execution. */
  async close(): Promise<void> { this.closed = true; this.active?.abort.abort(); await this.execution; this.listeners.clear(); }
}
