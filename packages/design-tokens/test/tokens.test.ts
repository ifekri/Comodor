import assert from "node:assert/strict";
import test from "node:test";

import {
  MODE, type Role, STAND_IN, TOKENS, WINDOW, cssVariables, desktop, isToken, roles, terminal,
} from "../src/index.ts";

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

test("every role has a value in the desktop theme", () => {
  for (const role of roles()) {
    assert.match(desktop[role], /^#[0-9a-f]{6}$/i, `${role} is not a colour`);
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
  const grounds: Role[] = ["surface.base", "surface.raised", "surface.overlay", "surface.selected",
    "surface.bar", "surface.panel", "surface.input", "surface.prompt"];
  const inks: Role[] = ["text.primary", "text.secondary", "text.muted", "text.accent",
    "semantic.success", "semantic.warning", "semantic.danger", "semantic.info", ...MODE];
  const pairs: [Role, Role][] = [
    ...grounds.flatMap((ground) => inks.map((ink) => [ink, ground] as [Role, Role])),
    ["text.primary", "surface.hover"], ["text.secondary", "surface.hover"],
    ["text.primary", "surface.active"], ["text.secondary", "surface.active"],
    ["text.primary", "surface.foot"], ["text.secondary", "surface.foot"], ["text.muted", "surface.foot"],
    ["text.primary", "surface.primary"],
    ["mode.act", "surface.act"], ["mode.act", "surface.chip"], ["mode.plan", "surface.plan"],
    ["mode.ask", "surface.ask"], ["mode.chat", "surface.chat"],
  ];
  const short = pairs
    .map(([ink, ground]) => ({ ink, ground, ratio: contrast(desktop[ink], desktop[ground]) }))
    .filter(({ ratio }) => ratio < 4.5);
  assert.deepEqual(short, []);
});

test("the desktop theme comes out as CSS custom properties too", () => {
  const css = cssVariables(desktop);
  assert.equal(css.split("\n").length, roles().length);
  assert.ok(css.includes("--surface-base: #191919;"));
  assert.ok(css.includes("--surface-bar: #1f1f1f;"));
});

test("the window's roles are roles, apart from the shared tokens", () => {
  for (const role of WINDOW) {
    assert.match(role, /^(surface|border|text|semantic|mode)\.[a-z]+$/);
    assert.doesNotMatch(role, /orange|blue|green|red|yellow|purple|grey|gray|white|black/i);
    assert.ok(!isToken(role), `${role} is also a shared token`);
  }
  assert.equal(new Set(roles()).size, roles().length);
});

test("the terminal mapping carries none of the window's roles; CSS gives it stand-ins", () => {
  // The terminal client bundles `terminal`; it stays exactly the shared tokens.
  assert.deepEqual(Object.keys(terminal).sort(), [...TOKENS].sort());
  const css = cssVariables();
  assert.equal(css.split("\n").length, roles().length);
  for (const role of WINDOW) {
    assert.ok(css.includes(`--${role.replace(/\./g, "-")}: ${terminal[STAND_IN[role]]};`), `${role} has no stand-in`);
  }
});
