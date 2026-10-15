import assert from "node:assert/strict";
import test from "node:test";

import { MODE, TOKENS, type Token, cssVariables, desktop, isToken, terminal } from "../src/index.ts";

test("every token has a value in the terminal theme", () => {
  // The type says so; this says so at runtime, which is what catches a theme
  // built by spreading another one and missing a key.
  for (const token of TOKENS) {
    assert.match(terminal[token], /^#[0-9a-f]{6}$/i, `${token} is not a colour`);
  }
});

test("no token is named after a colour", () => {
  // A token called `orange` is a colour wearing a name, and the second
  // renderer is where that stops working.
  for (const token of TOKENS) {
    assert.doesNotMatch(token,
      /orange|blue|green|red|yellow|purple|grey|gray|white|black/i);
  }
});

test("every token is a role in a group", () => {
  for (const token of TOKENS) {
    assert.match(token, /^(surface|border|text|semantic|mode)\.[a-z]+$/);
  }
});

test("there is a token for every mode, and only those", () => {
  assert.deepEqual([...MODE],
    ["mode.act", "mode.plan", "mode.ask", "mode.chat"]);
});

test("no two tokens are the same name", () => {
  assert.equal(new Set(TOKENS).size, TOKENS.length);
});

test("the act mode reads differently from the read-only ones", () => {
  // Act is the mode that can change things. If it looked like Plan, the one
  // visual signal that matters would be carrying no information.
  assert.notEqual(terminal["mode.act"], terminal["mode.plan"]);
  assert.notEqual(terminal["mode.act"], terminal["mode.ask"]);
});

test("isToken accepts a token and rejects a colour", () => {
  assert.ok(isToken("surface.base"));
  assert.ok(!isToken("#ff9d5c"));
  assert.ok(!isToken("surface"));
});

test("the same tokens come out as CSS custom properties", () => {
  // Not used by the terminal. It is the proof a token is renderer-independent:
  // anything that could not be expressed this way was not a token.
  const css = cssVariables();
  for (const token of TOKENS) {
    assert.ok(css.includes(`--${token.replace(/\./g, "-")}:`),
      `${token} has no CSS variable`);
  }
});

test("every token has a value in the desktop theme", () => {
  for (const token of TOKENS) {
    assert.match(desktop[token], /^#[0-9a-f]{6}$/i, `${token} is not a colour`);
  }
  assert.notEqual(desktop["mode.act"], desktop["mode.plan"]);
  assert.notEqual(desktop["mode.act"], desktop["mode.ask"]);
});

/** WCAG 2.1 relative luminance and contrast ratio. */
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((at) => {
    const value = parseInt(hex.slice(at, at + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

function contrast(one: string, other: string): number {
  const [light, dark] = [luminance(one), luminance(other)].sort((a, b) => b - a);
  return (light! + 0.05) / (dark! + 0.05);
}

test("desktop text reaches WCAG AA on every ground it is drawn on", () => {
  // The grounds text sits on, and the colours text is drawn in. `surface.hover`
  // carries only the two brightest text colours; the stylesheet keeps the rest off it.
  const grounds: Token[] = ["surface.base", "surface.raised", "surface.overlay", "surface.selected",
    "surface.bar", "surface.panel", "surface.input", "surface.prompt"];
  const inks: Token[] = ["text.primary", "text.secondary", "text.muted", "text.accent",
    "semantic.success", "semantic.warning", "semantic.danger", "semantic.info", ...MODE];
  const pairs: [Token, Token][] = [
    ...grounds.flatMap((ground) => inks.map((ink) => [ink, ground] as [Token, Token])),
    ["text.primary", "surface.hover"], ["text.secondary", "surface.hover"],
    ["text.primary", "surface.primary"],
    ["mode.act", "surface.act"], ["mode.plan", "surface.plan"],
    ["mode.ask", "surface.ask"], ["mode.chat", "surface.chat"],
  ];
  const short = pairs
    .map(([ink, ground]) => ({ ink, ground, ratio: contrast(desktop[ink], desktop[ground]) }))
    .filter(({ ratio }) => ratio < 4.5);
  assert.deepEqual(short, []);
});

test("the desktop theme comes out as CSS custom properties too", () => {
  const css = cssVariables(desktop);
  assert.equal(css.split("\n").length, TOKENS.length);
  assert.ok(css.includes("--surface-base: #191919;"));
});
