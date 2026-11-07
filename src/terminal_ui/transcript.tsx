import {Box, Text} from 'ink'; // Fixed-height viewport mounts only visible transcript rows.
import type {ReactElement} from 'react'; // Explicit component return contract.
import type {DisplayRow} from './contracts.js'; // Already laid-out rows; view contains no runtime logic.
import {THEME} from './theme.js'; // Shared role colors.

/** Transcript viewport. Args: formatted rows/start/height/width. Returns: clipped visible rows.
 * Globals: THEME. Calls: slice. Boundary: empty history fills the same height, preventing input movement. */
export function Transcript({rows, start, height, width}: {
  readonly rows: readonly DisplayRow[]; readonly start: number; readonly height: number; readonly width: number;
}): ReactElement {
  const colors = {normal: 'white', muted: THEME.muted, accent: THEME.accent, error: THEME.error};
  return <Box flexDirection="column" height={height} width={width} flexShrink={0} overflow="hidden">
    {rows.slice(start, start + height).map(row => <Text key={row.key} color={colors[row.tone]} wrap="truncate">{row.text || ' '}</Text>)}
  </Box>;
}
