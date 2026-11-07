/** One command definition drives input completion, help and the welcome card. */
export const COMMANDS = [
  {name: '/model', description: '模型配置', takesArgument: false},
  {name: '/file', description: '载入任务文件', takesArgument: true},
  {name: '/login', description: '登录秀米', takesArgument: false},
  {name: '/shot', description: '页面截图', takesArgument: false},
  {name: '/help', description: '帮助', takesArgument: false},
] as const;

/** Filter only the command token. Args: raw editor text. Returns: candidates; arguments close completion.
 * Globals: COMMANDS. Calls: String.trimStart/filter. Boundary: ordinary text or a completed token followed by space returns []. */
export function suggestions(text: string): typeof COMMANDS[number][] {
  const token = text.trimStart();
  return token.startsWith('/') && !/\s/.test(token) ? COMMANDS.filter(item => item.name.startsWith(token)) : [];
}
