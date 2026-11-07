import type {DisplayRow, TranscriptEntry, UiConfig, UiState} from './contracts.js'; // Strongly typed snapshots and refresh timing.
import {displayRows, initialState} from './presentation.js'; // Pure layout/reduction stays in the presentation layer.

/** Session-local snapshot storage. Attributes: state/listeners/timer own one UI lifecycle.
 * Lifecycle: construct -> update/subscribe -> dispose. Immediate data updates are coalesced only for rendering. */
export class SessionStore {
  private state: UiState = initialState(); // Latest authoritative state, including unflushed reasoning tokens.
  private published: UiState = this.state; // Stable React snapshot; getSnapshot never allocates objects.
  private readonly listeners = new Set<() => void>(); // Active view subscriptions.
  private timer: ReturnType<typeof setTimeout> | null = null; // One pending frame maximum.
  private disposed = false; // Prevents callbacks from reviving an unmounted UI.
  constructor(private readonly config: UiConfig) {}

  /** Read all received events, including the pending frame. Args: None. Returns: readonly state. Globals/Calls: None. */
  read = (): UiState => this.state;
  /** React external-store snapshot. Args: None. Returns: last published state. Globals/Calls: None. */
  snapshot = (): UiState => this.published;
  /** Subscribe to published frames. Args: listener. Returns: unsubscribe closure. Globals: None. Calls: Set.add/delete. */
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  /** Replace state and schedule one frame; task completion can force final delivery.
   * Args: new state/immediate flag. Returns: void. Globals: None. Calls: flush/setTimeout. Boundary: disposed/no change is ignored. */
  update(state: UiState, immediate = false): void {
    if (this.disposed || state === this.state) return;
    this.state = state;
    if (immediate) this.flush();
    else this.timer ??= setTimeout(() => this.flush(), this.config.frameMs);
  }
  /** Publish pending state. Args: None. Returns: void. Globals: None. Calls: subscribers; disposed stores stay inert. */
  flush(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.disposed || this.published === this.state) return;
    this.published = this.state;
    for (const listener of this.listeners) listener();
  }
  /** Release frame timer/subscribers. Args: None. Returns: void. Globals: None. Calls: clearTimeout/Set.clear; idempotent. */
  dispose(): void { this.disposed = true; if (this.timer) clearTimeout(this.timer); this.timer = null; this.listeners.clear(); }
}

/** Cache of immutable entry projections. Attributes: weak entry keys and one width/height projection per entry.
 * Lifecycle: created with App -> reuse stable history rows -> collected when App or entries are released.
 * Running thoughts bypass caching because their elapsed time changes without a new entry object. */
export class TranscriptCache {
  private readonly entries = new WeakMap<TranscriptEntry, {width: number; thinkingLines: number; rows: readonly DisplayRow[]}>(); // Weak keys never retain cleared history.

  /** Project only changed entries. Args: session, terminal width, clock, reasoning height. Returns: ordered rows.
   * Globals: None. Calls: displayRows. Boundary: a resize invalidates prior dimensions; raw text remains in the session. */
  project(state: UiState, width: number, now: number, thinkingLines: number): DisplayRow[] {
    const output: DisplayRow[] = [];
    for (const entry of state.entries) {
      const cached = this.entries.get(entry);
      const reusable = cached && cached.width === width && cached.thinkingLines === thinkingLines && !(entry.kind === 'thinking' && entry.status === 'running');
      const rows = reusable ? cached.rows : displayRows({...state, entries: [entry]}, width, now, thinkingLines);
      if (!reusable) this.entries.set(entry, {width, thinkingLines, rows});
      for (const row of rows) output.push(row);
    }
    return output;
  }
}
