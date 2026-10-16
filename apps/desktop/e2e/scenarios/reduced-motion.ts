/**
 * D2 T094: reduced motion in the real WebView (FR-020).
 *
 * In every run the stylesheet must turn the shell's motion off under
 * `prefers-reduced-motion: reduce`. With COMODOR_E2E_OS_LEVEL=1 the harness
 * also sets the operating system's preference for this run (and restores
 * it): the WebView must then report it, and the panel and the palette must
 * appear without animation or transition.
 *
 * Outcomes: `verified`; `capability-unavailable` (the preference could not
 * be set, or the WebView does not expose it through `matchMedia`);
 * `product-failure` (it is exposed, and the shell still moves). Only
 * `verified` passes; `not-run` (no OS level) is never evidence.
 */

import { expect, type Scenario } from "../runner.ts";

const QUERY = "(prefers-reduced-motion: reduce)";

/** The stylesheet has a reduced-motion rule that turns the shell's motion off. */
function stylesheetRule(): boolean {
  for (const sheet of [...document.styleSheets]) {
    let rules: CSSRuleList;
    try {
      rules = sheet.cssRules;
    } catch {
      continue;
    }
    for (const rule of [...rules]) {
      if (!(rule instanceof CSSMediaRule) || !rule.conditionText.includes("prefers-reduced-motion: reduce")) continue;
      // Read the parsed longhands: a shorthand may be serialised expanded.
      for (const inner of [...rule.cssRules]) {
        if (!(inner instanceof CSSStyleRule) || !inner.selectorText.includes(".shell")) continue;
        const style = inner.style;
        const noAnimation = style.getPropertyValue("animation-name") === "none";
        const noTransition = style.getPropertyValue("transition-property") === "none"
          || style.getPropertyValue("transition-duration") === "0s";
        if (noAnimation && noTransition) return true;
      }
    }
  }
  return false;
}

function still(element: Element | null): boolean {
  if (!element) return false;
  const style = getComputedStyle(element);
  const zero = (value: string) => value.split(",").every((part) => parseFloat(part) === 0);
  return (style.animationName === "none" || zero(style.animationDuration)) && zero(style.transitionDuration);
}

export const reducedMotion: Scenario = async (context) => {
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  await context.waitFor(() => document.querySelector('[data-testid="session"]'));
  expect(stylesheetRule(), "product-failure: the stylesheet has no reduced-motion rule for the shell");

  const reply = await context.checkpoint("reduced-motion");
  const motion = reply["motion"] as { applied: boolean; outcome?: string; reason?: string } | undefined;
  if (!motion?.applied && motion?.outcome === "not-run") {
    return { outcome: "not-run", reason: motion.reason, stylesheet: true };
  }
  if (!motion?.applied) throw new Error(`capability-unavailable: ${motion?.reason ?? "the preference was not set"}`);
  if (!window.matchMedia(QUERY).matches) {
    throw new Error("capability-unavailable: the WebView does not expose the preference through matchMedia");
  }

  const shell = document.querySelector('[data-testid="shell"]');
  expect(shell?.getAttribute("data-reduced-motion") === "true",
         "product-failure: the shell did not mark itself for reduced motion");
  document.querySelector<HTMLButtonElement>('nav[aria-label="Workbench"] button[aria-label="Core"]')!.click();
  const panel = await context.element('aside[aria-label="Core"]');
  expect(still(panel), `product-failure: the panel moves (${getComputedStyle(panel).animationName} ${
    getComputedStyle(panel).animationDuration})`);
  document.querySelector<HTMLButtonElement>('footer.status-bar button[aria-label="Commands"]')!.click();
  const palette = await context.element('[role="dialog"][aria-label="Commands"]');
  expect(still(palette), "product-failure: the palette moves");
  return { outcome: "verified", platform: navigator.userAgent };
};
