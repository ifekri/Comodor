/**
 * T036: the window's colours come only from the shared design tokens.
 */

import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";

import { cssVariables } from "@comodor/design-tokens";

import { applyTheme, tokenProperties } from "../src/theme.ts";

const STYLES = readFileSync(new URL("../src/styles.css", import.meta.url), "utf-8")
  .replace(/\/\*[\s\S]*?\*\//g, "");

describe("the theme", () => {
  test("every token from cssVariables() becomes a custom property", () => {
    const names = tokenProperties().map(([name]) => name);
    expect(names.length).toBe(cssVariables().split("\n").length);
    const root = document.createElement("div");
    applyTheme(root);
    for (const [name, value] of tokenProperties()) {
      expect(root.style.getPropertyValue(name)).toBe(value);
    }
  });

  test("the stylesheet holds no colour literal", () => {
    expect(STYLES).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(STYLES).not.toMatch(/\b(?:rgba?|hsla?|hwb|lab|lch|oklch|oklab|color)\(/);
    const named = /:\s*(?:white|black|red|green|blue|gray|grey|orange|yellow|purple)\b/;
    expect(STYLES).not.toMatch(named);
  });

  test("every variable the stylesheet uses is a design token", () => {
    const known = new Set(tokenProperties().map(([name]) => name));
    const used = [...STYLES.matchAll(/var\((--[\w-]+)\)/g)].map((match) => match[1]!);
    expect(used.length).toBeGreaterThan(0);
    expect(used.filter((name) => !known.has(name))).toEqual([]);
  });
});
