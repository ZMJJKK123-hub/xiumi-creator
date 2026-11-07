import {Text} from 'ink'; // Render only visible editor cells; input routing is owned by App.
import type {ReactElement} from 'react'; // Explicit component return contract.
import stringWidth from 'string-width'; // Cell-aware horizontal caret scrolling.
import type {EditorState} from './contracts.js'; // Input model is independent from Ink and the terminal.
import {graphemes, printable, summary} from './presentation.js'; // Unicode segmentation and display sanitization.
import {THEME} from './theme.js'; // Shared accent and placeholder colors.

/** Controlled editor view. Args: editor, cell budget, optional mask/focus/placeholder. Returns: one terminal row.
 * Globals: THEME. Calls: graphemes/stringWidth. Boundary: password glyphs never render raw; caret remains visible in narrow windows. */
export function TaskInput({editor, width, masked = false, focused = true, placeholder = ''}: {
  readonly editor: EditorState; readonly width: number; readonly masked?: boolean; readonly focused?: boolean; readonly placeholder?: string;
}): ReactElement {
  const budget = Math.max(1, width);
  const chars = graphemes(printable(editor.text)).map(char => masked ? '•' : char === '\n' ? '↵' : stringWidth(char) > budget ? ' ' : char);
  let start = editor.cursor;
  let used = stringWidth(chars[editor.cursor] ?? ' ');
  while (start > 0 && used + stringWidth(chars[start - 1] ?? '') <= budget) { start--; used += stringWidth(chars[start] ?? ''); }
  const visible: {text: string; index: number}[] = [];
  used = 0;
  for (let index = start; index <= chars.length; index++) {
    const char = chars[index] ?? ' ';
    if (used + stringWidth(char) > budget) break;
    visible.push({text: char, index}); used += stringWidth(char);
  }
  const from = Math.min(editor.cursor, editor.anchor ?? editor.cursor);
  const to = Math.max(editor.cursor, editor.anchor ?? editor.cursor);
  if (!editor.text && !focused) return <Text color={THEME.muted}>{placeholder}</Text>;
  return <Text>{visible.map(({text, index}) => <Text key={index} inverse={focused && (index === editor.cursor || (index >= from && index < to))}>{text}</Text>)}{!editor.text && placeholder && budget > 1 ? <Text color={THEME.muted}>{summary(placeholder, budget - 1)}</Text> : null}</Text>;
}
