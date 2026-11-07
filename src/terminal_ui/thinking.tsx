import {Text} from 'ink'; // Activity text is independent from transcript reasoning entries.
import type {ReactElement} from 'react'; // Component contract.
import type {UiState} from './contracts.js'; // Task lifecycle display input.
import {summary} from './presentation.js'; // Narrow-terminal clipping.
import {THEME} from './theme.js'; // Shared activity color.

/** Activity line. Args: state, frame clock and width. Returns: current task status, or empty text when idle.
 * Globals: THEME. Calls: summary. Boundary: clocks never show negative elapsed time; idle has no timer of its own. */
export function Activity({state, now, width}: {readonly state: UiState; readonly now: number; readonly width: number}): ReactElement {
  const frames = ['·', '✢', '✳', '✶', '✻', '✽'];
  const elapsed = Math.max(0, Math.floor((now - (state.task?.startedAt ?? now)) / 1000));
  const label = state.task?.status === 'cancelling' ? '正在中断' : 'thinking';
  return <Text color={THEME.accent}>{summary(`${frames[Math.floor(now / 120) % frames.length] ?? '✻'} ${label}… ${elapsed}s · Esc 中断`, width)}</Text>;
}
