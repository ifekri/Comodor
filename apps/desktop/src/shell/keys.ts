/**
 * The shell's keyboard: names for key events, the platform's primary
 * modifier, and the keys the shell never takes (FR-017; contracts/
 * workbench-shell.md, "Rules"). Bindings are written with `mod`, which is
 * Command on macOS and Control on Windows and Linux.
 */

export type Platform = "mac" | "other";

export interface KeyEventLike {
  readonly key: string;
  readonly shiftKey: boolean;
  readonly ctrlKey: boolean;
  readonly altKey: boolean;
  readonly metaKey: boolean;
}

export function platformOf(userAgent: string): Platform {
  return /Mac/i.test(userAgent) ? "mac" : "other";
}

/** The window's own platform. */
export function currentPlatform(): Platform {
  return platformOf(typeof navigator === "undefined" ? "" : navigator.userAgent);
}

export function modifierName(platform: Platform): "Cmd" | "Ctrl" {
  return platform === "mac" ? "Cmd" : "Ctrl";
}

/** A binding as a person reads it: `mod+k` becomes `Ctrl+K` or `Cmd+K`. */
export function displayKey(name: string, platform: Platform): string {
  return name.split("+").map((part, index, parts) => {
    if (part === "" && index === parts.length - 1) return "+";
    if (part === "mod") return modifierName(platform);
    if (part === "shift") return "Shift";
    if (part === "alt") return platform === "mac" ? "Option" : "Alt";
    if (/^f\d+$/.test(part)) return part.toUpperCase();
    if (part === "escape") return "Esc";
    if (part === "enter") return "Enter";
    return part.length === 1 ? part.toUpperCase() : part;
  }).join("+");
}

const MODIFIER_KEYS = new Set(["Control", "Shift", "Alt", "Meta", "AltGraph", "CapsLock", "OS"]);

/**
 * The name of a key event, or none. The other platform's modifier (Control
 * on macOS, the Windows key elsewhere) is never ours. Punctuation is named
 * by the character it produced, whether or not the keyboard layout needed
 * Shift for it; letters, digits and named keys keep their Shift state.
 */
export function keyName(event: KeyEventLike, platform: Platform): string | undefined {
  if (MODIFIER_KEYS.has(event.key)) return undefined;
  const mod = platform === "mac" ? event.metaKey : event.ctrlKey;
  const foreign = platform === "mac" ? event.ctrlKey : event.metaKey;
  if (foreign) return undefined;
  const base = event.key.toLowerCase();
  const punctuation = event.key.length === 1 && !/[\p{L}\p{N}]/u.test(event.key);
  const parts: string[] = [];
  if (mod) parts.push("mod");
  if (event.altKey) parts.push("alt");
  if (event.shiftKey && !punctuation) parts.push("shift");
  parts.push(base);
  return parts.join("+");
}

const MOVEMENT = new Set(["arrowleft", "arrowright", "arrowup", "arrowdown", "home", "end", "pageup", "pagedown"]);
const RESERVED = new Set([
  "tab", "shift+tab",
  "mod+a", "mod+c", "mod+x", "mod+v", "mod+z", "mod+y", "mod+shift+z",
  "mod+w", "mod+q", "mod+m", "mod+h", "mod+.",
  "alt+f4", "mod+r", "f5", "mod+=", "mod++", "mod+-", "mod+0",
]);

/** Whether the platform, the WebView or text editing needs this key. */
export function isReserved(name: string): boolean {
  if (RESERVED.has(name)) return true;
  const parts = name.split("+");
  const last = parts.at(-1) === "" ? "+" : parts.at(-1)!;
  // Text-editing movement and selection, with or without mod, Shift or Alt.
  if (MOVEMENT.has(last)) return true;
  // An unmodified printable key, Shift or not, is text.
  const modified = parts.includes("mod") || parts.includes("alt");
  return !modified && last.length === 1;
}

/**
 * Whether a key typed in a text field reaches the shell: only modified keys
 * and F6. Enter and Escape in the composer keep D1's meaning there, so the
 * shell leaves them to the composer.
 */
export function reachesShell(name: string, inTextField: boolean): boolean {
  if (!inTextField) return true;
  if (name === "f6" || name === "shift+f6") return true;
  const parts = name.split("+");
  return parts.includes("mod") || parts.includes("alt");
}

const TEXT_INPUT_TYPES = new Set(["text", "search", "url", "tel", "email", "password", "number", ""]);

export function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target instanceof HTMLTextAreaElement) return true;
  if (target instanceof HTMLInputElement) return TEXT_INPUT_TYPES.has(target.type);
  return target.isContentEditable || target.getAttribute("contenteditable") === "true";
}
