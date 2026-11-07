import {Box, Text, useApp, useInput, usePaste, useStdin, useWindowSize} from 'ink'; // Declarative terminal layout and a single input owner.
import {useEffect, useMemo, useRef, useState, useSyncExternalStore} from 'react'; // View lifecycle, stable session snapshots and transient editing state.
import type {ReactElement} from 'react'; // Explicit UI component contract.
import type {EditorState, IntentResult, ModalState, ScrollAnchor, TerminalPort} from './contracts.js'; // Typed UI and platform boundaries.
import {COMMANDS, suggestions} from './command_catalog.js'; // Unified command definitions.
import {UiController} from './controller.js'; // Runtime orchestration injected into the view.
import {HelpDialog, ModelDialog} from './dialogs.js'; // Focus-isolated dialog views.
import {editText, graphemes, isBusy, summary, viewportStart} from './presentation.js'; // Pure state-to-layout/edit transformations.
import {TranscriptCache} from './session_store.js'; // Stable immutable history projections avoid rewrapping every message on token updates.
import {TaskInput} from './task_input.js'; // Shared masked/unmasked controlled input view.
import {Activity} from './thinking.js'; // Busy-only activity line.
import {Transcript} from './transcript.js'; // Virtual visible-row rendering.
import {THEME, UI_VERSION} from './theme.js'; // Shared visual tokens.

const EMPTY_EDITOR: EditorState = {text: '', cursor: 0, anchor: null}; // Immutable empty editor seed.

/** Build an editor at the end of existing text. Args: text. Returns: editor. Globals: None. Calls: graphemes. */
function editorFor(text: string): EditorState { return {text, cursor: graphemes(text).length, anchor: null}; }

/** TS rendering root. Attributes live in hooks: input/form/modal/anchor and the selected reasoning round.
 * Lifecycle: subscribe on mount -> project state into visible rows -> remove timers/wheel subscription on unmount.
 * Args: injected controller/terminal, optional test dimensions. Returns: full-screen UI; tiny terminals keep the editor visible.
 * Globals: THEME/COMMANDS/UI_VERSION. Calls: controller actions and Ink hooks; components perform no browser or configuration I/O. */
export function TerminalApp({controller, terminal, dimensions}: {
  readonly controller: UiController; readonly terminal: TerminalPort; readonly dimensions?: {readonly columns: number; readonly rows: number};
}): ReactElement {
  const windowSize = useWindowSize();
  const width = Math.max(8, dimensions?.columns ?? windowSize.columns);
  const height = Math.max(4, dimensions?.rows ?? windowSize.rows);
  const state = useSyncExternalStore(controller.store.subscribe, controller.store.snapshot, controller.store.snapshot);
  const {exit} = useApp();
  const {isRawModeSupported} = useStdin();
  const [editor, setEditor] = useState<EditorState>(EMPTY_EDITOR);
  const [modal, setModal] = useState<ModalState>({type: 'none'});
  const [fields, setFields] = useState<readonly EditorState[]>([EMPTY_EDITOR, EMPTY_EDITOR, EMPTY_EDITOR]);
  const [focus, setFocus] = useState(0);
  const [formStatus, setFormStatus] = useState('');
  const [candidate, setCandidate] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const [anchor, setAnchor] = useState<ScrollAnchor | null>(null);
  const [selectedRound, setSelectedRound] = useState<string | undefined>(undefined);
  const [now, setNow] = useState(Date.now());
  const [layoutCache] = useState(() => new TranscriptCache());
  const pending = useRef(false); // Serializes accepted submissions/config writes, not runtime task execution.
  const mounted = useRef(true); // Async clipboard/config completions cannot modify an unmounted view.
  const focusRef = useRef({modal: modal.type, focus}); // Prevents slow clipboard reads from landing in a different field.
  focusRef.current = {modal: modal.type, focus};
  const busy = isBusy(state);
  const candidates = dismissed ? [] : suggestions(editor.text);
  const index = candidates.length ? candidate % candidates.length : 0;
  const headerHeight = width < 64 ? 3 : 4;
  const candidateRows = Math.min(candidates.length, Math.max(0, height - headerHeight - 6));
  const candidateStart = Math.max(0, index - candidateRows + 1);
  const transcriptHeight = Math.max(0, height - headerHeight - 4 - candidateRows - (busy ? 1 : 0));
  const rows = useMemo(() => layoutCache.project(state, width, now, controller.config.thinkingLines), [layoutCache, state, width, now, controller.config.thinkingLines]);
  const start = viewportStart(rows, anchor, transcriptHeight);
  const scrollRef = useRef<(delta: number) => void>(() => undefined);
  scrollRef.current = delta => {
    const max = Math.max(0, rows.length - transcriptHeight);
    const target = Math.max(0, Math.min(max, start + delta));
    const row = rows[target];
    setAnchor(target >= max || !row ? null : {entryId: row.entryId, row: target - rows.findIndex(item => item.entryId === row.entryId)});
  };

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => terminal.subscribeWheel(direction => { if (focusRef.current.modal === 'none') scrollRef.current(direction * 3); }), [terminal]);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => setNow(Date.now()), 120);
    return () => clearInterval(timer);
  }, [busy]);
  useEffect(() => { setSelectedRound(undefined); }, [state.task?.id]);

  // Reset secret fields whenever a modal is closed, including cancellation and successful save.
  const closeModal = (): void => { setModal({type: 'none'}); setFields([EMPTY_EDITOR, EMPTY_EDITOR, EMPTY_EDITOR]); setFormStatus(''); };
  const insert = (text: string): void => {
    if (modal.type === 'help') return;
    const apply = (value: EditorState): EditorState => {
      const next = editText(value, {type: 'insert', text});
      return next.text.length <= controller.config.maxTaskChars ? next : value;
    };
    if (modal.type === 'model') setFields(values => values.map((value, field) => field === focus ? apply(value) : value));
    else { setEditor(apply); setDismissed(false); setCandidate(0); }
  };
  const report = (result: IntentResult): void => { if (result.type === 'rejected') controller.notice(result.message); };
  const saveModel = async (): Promise<void> => {
    if (pending.current) return;
    pending.current = true;
    setFormStatus('正在保存…');
    try {
      const result = await controller.send({type: 'save_model', model: fields[0]?.text ?? '', apiKey: fields[1]?.text ?? '', baseUrl: fields[2]?.text ?? ''});
      if (!mounted.current || focusRef.current.modal !== 'model') return;
      if (result.type === 'rejected') setFormStatus(result.message);
      else { closeModal(); controller.notice('预览配置已更新，仅在本次运行中生效'); }
    } finally { pending.current = false; }
  };
  const submit = async (raw: string): Promise<void> => {
    if (!raw.trim() || pending.current) return;
    const token = raw.trim().split(/\s/, 1)[0] ?? '';
    if (token === '/help') { setEditor(EMPTY_EDITOR); setModal({type: 'help'}); return; }
    if (token === '/model') {
      setEditor(EMPTY_EDITOR); setFields([editorFor(state.model.model), EMPTY_EDITOR, editorFor(state.model.baseUrl)]);
      setFocus(0); setFormStatus(''); setModal({type: 'model'}); return;
    }
    pending.current = true;
    try {
      let result: IntentResult;
      switch (token) {
        case '/file': {
          result = await controller.send({type: 'load_file', path: raw.trim().slice(token.length).trim()});
          if (result.type === 'task_text') result = await controller.send({type: 'submit_task', text: result.text});
          break;
        }
        case '/login': result = await controller.send({type: 'login'}); break;
        case '/shot': result = await controller.send({type: 'capture'}); break;
        default: result = token.startsWith('/') ? {type: 'rejected', code: 'invalid_input', message: '未知命令，/help 查看帮助'} : await controller.send({type: 'submit_task', text: raw});
      }
      if (result.type === 'accepted') { setEditor(EMPTY_EDITOR); setAnchor(null); }
      else report(result);
    } finally { pending.current = false; }
  };

  usePaste(text => { if (!pending.current) insert(text); }, {isActive: isRawModeSupported});
  useInput((input, key) => {
    if (key.eventType === 'release') return;
    if (key.ctrl && (input === 'q' || input === 'c')) { exit(); return; }
    if (modal.type === 'help') { closeModal(); return; }
    if (key.escape) {
      if (modal.type !== 'none') closeModal();
      else if (candidates.length) setDismissed(true);
      else void controller.interrupt();
      return;
    }
    if (pending.current) return;
    if (key.ctrl && input === 'v' || key.shift && input === '\x1b[2~') {
      const target = {...focusRef.current};
      void terminal.readClipboard().then(text => {
        if (mounted.current && target.modal === focusRef.current.modal && target.focus === focusRef.current.focus) insert(text);
      }).catch(() => {
        if (!mounted.current) return;
        if (modal.type === 'model') setFormStatus('系统剪贴板不可用，请使用终端粘贴');
        else controller.notice('系统剪贴板不可用，请使用终端粘贴');
      });
      return;
    }
    if (modal.type === 'model') {
      if (key.tab) { setFocus(value => (value + (key.shift ? 2 : 1)) % 3); return; }
      if (key.return) { if (focus < 2) setFocus(focus + 1); else void saveModel(); return; }
    } else {
      if (key.ctrl && input === 'l') { controller.clear(); setAnchor(null); return; }
      if (key.ctrl && input === 'o') { controller.toggleThinking(selectedRound); return; }
      if (key.meta && (key.leftArrow || key.rightArrow)) {
        const thoughts = state.entries.filter(entry => entry.kind === 'thinking' && entry.text);
        const current = selectedRound ? thoughts.findIndex(entry => entry.id === selectedRound) : thoughts.length - 1;
        setSelectedRound(thoughts[Math.max(0, Math.min(thoughts.length - 1, current + (key.leftArrow ? -1 : 1)))]?.id); return;
      }
      if (key.ctrl && (key.upArrow || key.downArrow)) {
        const id = selectedRound ?? state.entries.findLast(entry => entry.kind === 'thinking')?.id;
        if (id) controller.scrollThinking(id, key.upArrow ? 1 : -1, width);
        return;
      }
      if (key.pageUp || key.pageDown) { scrollRef.current((key.pageUp ? -1 : 1) * Math.max(1, transcriptHeight - 1)); return; }
      if (key.end && !editor.text) { setAnchor(null); return; }
      if (candidates.length && (key.tab || key.upArrow || key.downArrow)) {
        const delta = key.shift || key.upArrow ? -1 : 1;
        setCandidate(value => (value + delta + candidates.length) % candidates.length); return;
      }
      if (key.return) {
        const choice = candidates[index];
        if (choice && choice.takesArgument) { setEditor(editorFor(choice.name + ' ')); setDismissed(true); }
        else void submit(choice?.name ?? editor.text);
        return;
      }
    }
    const update = (value: EditorState): EditorState => {
      if (key.ctrl && input === 'a') return editText(value, {type: 'select_all'});
      if (key.leftArrow || key.rightArrow) return editText(value, {type: 'move', delta: key.leftArrow ? -1 : 1, select: key.shift});
      if (key.home || key.end) return editText(value, {type: key.home ? 'home' : 'end', select: key.shift});
      if (key.backspace || key.delete) return editText(value, {type: key.backspace ? 'backspace' : 'delete'});
      return value;
    };
    if (key.ctrl || key.meta || key.leftArrow || key.rightArrow || key.home || key.end || key.backspace || key.delete) {
      if (modal.type === 'model') setFields(values => values.map((value, field) => field === focus ? update(value) : value));
      else { setEditor(update); setDismissed(false); }
    } else if (input && !key.tab && !key.upArrow && !key.downArrow && !/\x1b|\[<\d+;/.test(input)) insert(input);
  }, {isActive: isRawModeSupported});

  if ((height - headerHeight < 8 || width < 32) && modal.type === 'model') return <Box width={width} height={height} flexDirection="column" overflow="hidden">
    <Text color={THEME.accent}>{summary(`配置 ${['模型', '密钥', '地址'][focus] ?? ''} · 预览`, width)}</Text>
    <TaskInput editor={fields[focus] ?? EMPTY_EDITOR} width={width} masked={focus === 1}/>
    <Text color={THEME.error}>{summary(formStatus || 'Tab 切换 · Enter 下一项/保存', width)}</Text>
    <Text color={THEME.muted}>{summary('Esc 取消 · Ctrl+Q 退出', width)}</Text>
  </Box>;
  if (height < 10 && modal.type === 'help') return <HelpDialog width={width} height={height}/>;
  if (height < 10) return <Box width={width} height={height} flexDirection="column" overflow="hidden">
    <Text color={THEME.accent}>{summary('xiumi · 渲染预览 · 请增大窗口', width)}</Text>
    <Transcript rows={rows} start={viewportStart(rows, anchor, height - 3)} height={height - 3} width={width}/>
    <TaskInput editor={editor} width={width} placeholder="输入任务"/>
    <Text color={THEME.muted}>{summary('Ctrl+Q 退出 · Esc 中断', width)}</Text>
  </Box>;
  return <Box width={width} height={height} flexDirection="column" overflow="hidden">
    <Box borderStyle="round" borderColor={THEME.accent} flexDirection="column" height={headerHeight} flexShrink={0}>
      <Text bold color={THEME.accent}>{summary(`xiumi-agent ${UI_VERSION} · 渲染预览 / 模拟运行`, width - 2)}</Text>
      {width >= 64 ? <Text color={THEME.muted}>{summary(`模型: ${state.model.model || '未配置'} · ${state.loggedIn ? '模拟已登录' : '未登录'}   ${COMMANDS.map(command => command.name).join(' ')}`, width - 2)}</Text> : null}
    </Box>
    {modal.type === 'help' ? <HelpDialog width={width} height={height - headerHeight}/> : modal.type === 'model'
      ? <ModelDialog fields={fields} focus={focus} status={formStatus} width={width} height={height - headerHeight}/>
      : <>
        <Transcript rows={rows} start={start} height={transcriptHeight} width={width}/>
        {busy ? <Activity state={state} now={now} width={width}/> : null}
        {candidates.slice(candidateStart, candidateStart + candidateRows).map((command, position) => <Text key={command.name} color={position + candidateStart === index ? THEME.accent : THEME.muted}>{summary(`${position + candidateStart === index ? '›' : ' '} ${command.name}  ${command.description}`, width)}</Text>)}
        <Box borderStyle="round" borderColor={THEME.border} height={3} flexShrink={0}><Text color={THEME.accent}>&gt; </Text><TaskInput editor={editor} width={width - 4} placeholder="输入任务，或 / 查看命令"/></Box>
        <Text color={THEME.muted}>{summary(`${anchor ? '历史阅读 · End 回到底部' : 'PgUp/PgDn 翻页'} · Ctrl+O 思考 · Ctrl+Q 退出${selectedRound ? ' · 已选择历史轮次' : ''}`, width)}</Text>
      </>}
  </Box>;
}
