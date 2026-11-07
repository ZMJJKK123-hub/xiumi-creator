import {execFile} from 'node:child_process'; // Fixed clipboard helper command; user input is never interpolated into a shell.
import type {Readable, Writable} from 'node:stream'; // Stream injection permits terminal-mode and wheel tests.
import type {TerminalPort, UiConfig} from './contracts.js'; // Platform capability contract and timeout injection.

/** Read SGR wheel packets. Args: a terminal chunk. Returns: all scroll directions; clicks/motion are ignored.
 * Globals: None. Calls: matchAll. Boundary: wheel packets may arrive batched; packet buffering is performed by subscribeWheel. */
export function wheelDirections(chunk: string): (-1 | 1)[] {
  const output: (-1 | 1)[] = [];
  for (const match of chunk.matchAll(/\x1b\[<(\d+);\d+;\d+[Mm]/g)) {
    const button = Number(match[1]);
    if ((button & 64) !== 0) output.push((button & 1) === 0 ? -1 : 1);
  }
  return output;
}

/** Terminal adapter. Args: input/output streams and timing config. Returns: clipboard/wheel capabilities.
 * Globals: process.platform. Calls: execFile/stream.on/write. Boundary: unsupported clipboard rejects; teardown always disables mouse reporting. */
export function createTerminalPort(input: Readable, output: Writable, config: UiConfig): TerminalPort {
  return {
    readClipboard: () => new Promise<string>((resolve, reject) => {
      if (process.platform !== 'win32') { reject(new Error('SystemClipboardUnavailable')); return; }
      execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', '[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw'],
        {encoding: 'utf8', timeout: config.clipboardTimeoutMs, windowsHide: true, maxBuffer: config.maxFileBytes},
        (error, stdout) => error ? reject(error) : resolve(stdout.replace(/\r\n/g, '\n').replace(/\n$/, '')));
    }),
    subscribeWheel(listener) {
      let tail = '';
      const handler = (chunk: Buffer | string): void => {
        const text = tail + String(chunk);
        for (const direction of wheelDirections(text)) listener(direction);
        const start = text.lastIndexOf('\x1b[<');
        tail = start >= 0 && !/[Mm]/.test(text.slice(start)) ? text.slice(start, start + 64) : '';
      };
      output.write('\x1b[?1000h\x1b[?1006h');
      input.on('data', handler);
      return () => { input.off('data', handler); output.write('\x1b[?1000l\x1b[?1006l'); };
    },
  };
}
