import {appendFileSync, mkdirSync} from 'node:fs'; // Central file logging keeps diagnostic output away from Ink's stdout.
import {join} from 'node:path'; // Portable diagnostic file location.
import type {LoggerPort} from '../terminal_ui/contracts.js'; // Renderer depends on this abstraction, not filesystem logging.

/** Create a redacted structured logger. Args: log directory/session trace ID. Returns: logger.
 * Globals: None. Calls: mkdirSync/appendFileSync. Boundary: only class/stack frames/operation are logged, never payloads or exception messages; I/O errors propagate to the controller boundary. */
export function createLogger(directory: string, traceId: string): LoggerPort {
  mkdirSync(directory, {recursive: true});
  return {error(operation, error): void {
    appendFileSync(join(directory, 'terminal-ui.log'), JSON.stringify({at: new Date().toISOString(), level: 'ERROR', traceId, operation,
      error: error instanceof Error ? error.name : 'UnknownError', stack: error instanceof Error ? error.stack?.split('\n').filter(line => /^\s+at\s/.test(line)) : []}) + '\n');
  }};
}
