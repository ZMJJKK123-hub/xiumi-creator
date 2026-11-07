import type {UiConfig} from './contracts.js'; // Shared configuration contract keeps timing outside components.

/** Visual tokens, terminal constraints and refresh policy used by the whole rendering layer. */
export const THEME = {accent: '#E06C38', muted: '#8E8E8E', error: '#E05252', border: '#cfcfcf'} as const;
export const DEFAULT_UI_CONFIG: UiConfig = {
  frameMs: 50, previewStepMs: 160, clipboardTimeoutMs: 2000,
  maxTaskChars: 100_000, maxFileBytes: 2 * 1024 * 1024, thinkingLines: 5,
};
export const UI_VERSION = '0.1.0'; // Separate preview version; the existing Python release stays identifiable.
