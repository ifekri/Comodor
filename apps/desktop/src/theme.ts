/**
 * The window's colours: the shared design tokens, as CSS custom properties.
 *
 * `cssVariables()` is the one source; every colour in `styles.css` is a
 * `var(--token)`. The properties are set through the CSSOM rather than an
 * inline `<style>`, which the Content Security Policy does not allow.
 */

import { cssVariables } from "@comodor/design-tokens";

/** `--name: value;` lines, as `cssVariables()` writes them. */
export function tokenProperties(): [string, string][] {
  return cssVariables().split("\n").flatMap((line) => {
    const match = /^\s*(--[\w-]+):\s*(.+);\s*$/.exec(line);
    return match ? [[match[1]!, match[2]!] as [string, string]] : [];
  });
}

export function applyTheme(root: HTMLElement = document.documentElement): void {
  for (const [name, value] of tokenProperties()) root.style.setProperty(name, value);
}
