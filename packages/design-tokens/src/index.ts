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
 *
 * Every role is emitted, the window's (`WINDOW`, below) included; a theme
 * without them, like the terminal's, gives each its stand-in's colour.
 */
export function cssVariables(theme: Theme | WindowTheme = terminal): string {
  const colours: Partial<Record<Role, string>> = theme;
  return roles()
    .map((role) => `  --${role.replace(/\./g, "-")}: ${colours[role] ?? theme[STAND_IN[role as WindowRole]]};`)
    .join("\n");
}

/**
 * The desktop window's finer roles (Feature 004): its bars, its panels, a
 * field, the prompt, a row under the pointer, the primary action, each mode's
 * own ground, a floating layer's shadow, a strong and a subtle border, and an
 * accent for text. Roles like the others, kept in their own list so the
 * terminal mapping above stays exactly as it is: the terminal draws none of
 * them, and `cssVariables` gives each one a terminal stand-in.
 */
export const WINDOW = [
  "surface.bar",
  "surface.panel",
  "surface.input",
  "surface.prompt",
  "surface.hover",
  "surface.primary",
  "surface.act",
  "surface.plan",
  "surface.ask",
  "surface.chat",
  "surface.shadow",
  "surface.active",
  "surface.foot",
  "surface.backdrop",
  "surface.chip",
  "border.strong",
  "border.subtle",
  "border.tile",
  "text.accent",
  // D3a: a file's text in the read-only viewer, coloured by what each part is.
  "text.code",
  "text.keyword",
  "text.string",
  "text.number",
  "text.type",
  "text.function",
  "text.property",
  "text.tag",
  "text.comment",
  "text.punctuation",
] as const;

export type WindowRole = (typeof WINDOW)[number];

export type Role = Token | WindowRole;

/**
 * Every role a CSS mapping emits: the shared tokens, then the window's. A
 * function rather than a constant, so a client that never asks for it (the
 * terminal) bundles none of the window's roles.
 */
export function roles(): readonly Role[] {
  return [...TOKENS, ...WINDOW];
}

/** A mapping for a renderer that draws the window's roles too. */
export type WindowTheme = Readonly<Record<Role, string>>;

/** For a theme without the window's roles, the shared token each one falls back to. */
export const STAND_IN: Readonly<Record<WindowRole, Token>> = {
  "surface.bar": "surface.raised",
  "surface.panel": "surface.raised",
  "surface.input": "surface.base",
  "surface.prompt": "surface.base",
  "surface.hover": "surface.selected",
  "surface.primary": "surface.selected",
  "surface.act": "surface.selected",
  "surface.plan": "surface.selected",
  "surface.ask": "surface.selected",
  "surface.chat": "surface.selected",
  "surface.shadow": "surface.base",
  "surface.active": "surface.selected",
  "surface.foot": "surface.raised",
  "surface.backdrop": "surface.base",
  "surface.chip": "surface.selected",
  "border.strong": "border.default",
  "border.subtle": "border.default",
  "border.tile": "border.default",
  "text.accent": "border.focused",
  "text.code": "text.primary",
  "text.keyword": "mode.plan",
  "text.string": "semantic.success",
  "text.number": "semantic.warning",
  "text.type": "mode.plan",
  "text.function": "semantic.info",
  "text.property": "text.secondary",
  "text.tag": "semantic.danger",
  "text.comment": "text.muted",
  "text.punctuation": "text.muted",
};

/**
 * The desktop window's mapping (Feature 004): a neutral dark ground with a
 * cyan focus, after the owner's reference design.
 *
 * Every text colour here reaches WCAG 2.1 AA (4.5:1) on every ground it is
 * drawn on. Where the reference's grey or red fell short — `text.muted`
 * (#8a8a8a there) and `semantic.danger` (#e0605a there) on the raised
 * grounds — the nearest value that passes is used instead, and the
 * reference's dimmer greys are not used for text at all.
 */
export const desktop: WindowTheme = {
  "surface.base": "#191919",
  "surface.raised": "#2a2a2a",
  "surface.overlay": "#272727",
  "surface.selected": "#1b2b2f",
  "surface.bar": "#1f1f1f",
  "surface.panel": "#242424",
  "surface.input": "#1c1c1c",
  "surface.prompt": "#1d1d1d",
  "surface.hover": "#333333",
  "surface.primary": "#2f5a3e",
  "surface.act": "#163824",
  "surface.plan": "#173a44",
  "surface.ask": "#1d2a33",
  "surface.chat": "#262626",
  "surface.shadow": "#000000",
  "surface.active": "#2c2c2c",
  "surface.foot": "#212121",
  "surface.backdrop": "#0c0c0c",
  "surface.chip": "#1e2a22",

  "border.default": "#3a3a3a",
  "border.focused": "#5fd4e8",
  "border.active": "#3fa9bc",
  "border.strong": "#424242",
  "border.subtle": "#333333",
  "border.tile": "#4a4a4a",

  "text.primary": "#e6e6e6",
  "text.secondary": "#b8b8b8",
  "text.muted": "#929292",
  "text.accent": "#5fd4e8",
  // The reference's syntax colours (its §6.3). Where its comment, punctuation
  // and tag colours fall below AA on the code ground or on a selection, the
  // nearest passing value is used.
  "text.code": "#d6d6d6",
  "text.keyword": "#5fd4e8",
  "text.string": "#7fd39a",
  "text.number": "#e0a04a",
  "text.type": "#9be6f2",
  "text.function": "#8ab8ff",
  "text.property": "#cdb892",
  "text.tag": "#e66a64",
  "text.comment": "#929292",
  "text.punctuation": "#9a9a9a",

  "semantic.success": "#35c46a",
  "semantic.warning": "#e0a04a",
  "semantic.danger": "#e66a64",
  "semantic.info": "#3fa2e0",

  // Act changes things and reads green; Plan is the cyan of focus; Ask is blue.
  "mode.act": "#35c46a",
  "mode.plan": "#5fd4e8",
  "mode.ask": "#3fa2e0",
  "mode.chat": "#b8b8b8",
};
