import assert from "node:assert/strict";
import test from "node:test";

import { MODE, TOKENS, cssVariables, isToken, terminal } from "../src/index.ts";

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
