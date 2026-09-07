/**
 * Semantic names for what things mean, separate from what they look like.
 *
 * The reason for the split is the second renderer. A terminal has 16 reliable
 * colours, a truecolour terminal has more, and a browser has CSS variables and
 * a media query for dark mode. If a component says `#ff9d5c`, all three are
 * stuck with it; if it says `mode.act`, each maps that name to whatever it can
 * actually draw, and the component is unchanged.
 *
 * So a token names a *role* — `surface.raised`, `border.focused`,
 * `semantic.danger` — and never a colour. `terminal()` below is the first
 * mapping; a future Tauri client adds a second that emits CSS variables from
 * the same list, which is what makes "the same design in two renderers" a
 * mechanical claim rather than an aspiration.
 */

export const SURFACE = [
  "surface.base",
  "surface.raised",
  "surface.overlay",
  "surface.selected",
] as const;

export const BORDER = [
  "border.default",
  "border.focused",
  "border.active",
] as const;

export const TEXT = [
  "text.primary",
  "text.secondary",
  "text.muted",
] as const;

export const SEMANTIC = [
  "semantic.success",
  "semantic.warning",
  "semantic.danger",
  "semantic.info",
] as const;

export const MODE = [
  "mode.act",
  "mode.plan",
  "mode.ask",
  "mode.chat",
] as const;

export const TOKENS = [
  ...SURFACE, ...BORDER, ...TEXT, ...SEMANTIC, ...MODE,
] as const;

export type Token = (typeof TOKENS)[number];

export function isToken(value: unknown): value is Token {
  return typeof value === "string" && (TOKENS as readonly string[]).includes(value);
}

/**
 * One theme: every token, and nothing else.
 *
 * `Record<Token, string>` rather than a partial, so adding a token is a
 * compile error in every theme rather than a colour that silently falls back
 * to whatever the terminal had.
 */
export type Theme = Readonly<Record<Token, string>>;

/**
 * The terminal mapping, as 24-bit hex.
 *
 * Hex rather than ANSI indices because OpenTUI takes colours and degrades
 * them itself, and because the same strings are what a CSS mapping will want.
 * Chosen to stay legible on a dark ground, which is what a terminal running a
 * coding agent overwhelmingly is.
 */
export const terminal: Theme = {
  "surface.base": "#0d0b0a",
  "surface.raised": "#16120f",
  "surface.overlay": "#1e1815",
  "surface.selected": "#2a211b",

  "border.default": "#3a2f27",
  "border.focused": "#ff9d5c",
  "border.active": "#c8794a",

  "text.primary": "#e8e0d8",
  "text.secondary": "#b8aca2",
  "text.muted": "#7d726a",

  "semantic.success": "#7fb069",
  "semantic.warning": "#e0b354",
  "semantic.danger": "#d4664f",
  "semantic.info": "#6ba3c4",

  // Act is the one that can change things, so it is the one that reads as
  // "live". Plan and Ask are calmer on purpose: the colour should not make a
  // read-only mode look like it is about to do something.
  "mode.act": "#ff9d5c",
  "mode.plan": "#6ba3c4",
  "mode.ask": "#a99bd4",
  "mode.chat": "#7d726a",
};

/**
 * The same tokens as CSS custom properties.
 *
 * Not used by the terminal client. It is here because it is the proof that a
 * token is renderer-independent: if a token could not be expressed this way,
 * it was a colour wearing a name.
 */
export function cssVariables(theme: Theme = terminal): string {
  return TOKENS
    .map((token) => `  --${token.replace(/\./g, "-")}: ${theme[token]};`)
    .join("\n");
}
