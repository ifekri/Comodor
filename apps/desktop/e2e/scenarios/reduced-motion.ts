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

function capabilityUnavailable(reason: string): Error {
  return new Error(`capability-unavailable: ${reason}`);
}

/** The computed motion of `element`, as the page sees it. */
function motionOf(element: Element): { animation: string; duration: string; transition: string } {
  const style = getComputedStyle(element);
  return { animation: style.animationName, duration: style.animationDuration, transition: style.transitionDuration };
}

/**
 * D2 follow-up: one phase of the macOS off-to-on transition. The harness has
 * switched the operating system's preference and confirmed its effective
 * value before this launch. Off: the WebView must report no reduced motion,
 * and the panel must ease in (so the "on" result below is the preference's
 * doing). On: the WebView must report it, and the panel and the palette must
 * have zero-duration motion. A WebView that does not follow the operating
 * system is `capability-unavailable`; a shell that does not follow the WebView
 * is `product-failure`.
 */
export const reducedMotionTransition: Scenario = async (context) => {
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  await context.waitFor(() => document.querySelector('[data-testid="session"]'));
  const reply = await context.checkpoint("motion-phase");
  const phase = reply["phase"] as { phase?: "off" | "on"; outcome?: string; reason?: string } | undefined;
  if (!phase?.phase) return { outcome: phase?.outcome ?? "not-run", reason: phase?.reason ?? "no phase was set" };

  const reported = window.matchMedia(QUERY).matches;
  const marked = document.querySelector('[data-testid="shell"]')?.getAttribute("data-reduced-motion");
  document.querySelector<HTMLButtonElement>('nav[aria-label="Workbench"] button[aria-label="Core"]')!.click();
  const panel = await context.element('aside[aria-label="Core"]');
  const panelMotion = motionOf(panel);

  if (phase.phase === "off") {
    if (reported) {
      throw capabilityUnavailable("the WebView reports reduced motion although the operating system reports it off");
    }
    expect(marked === "false", `product-failure: the shell marked itself for reduced motion with it off (${marked})`);
    expect(!still(panel), `product-failure: with reduced motion off the panel does not ease in (${
      JSON.stringify(panelMotion)})`);
    return { outcome: "verified", phase: "off", matchMedia: reported, marked, panel: panelMotion };
  }

  if (!reported) {
    throw capabilityUnavailable("the WebView does not report reduced motion although the operating system reports it on");
  }
  expect(marked === "true", `product-failure: the shell did not mark itself for reduced motion (${marked})`);
  expect(still(panel), `product-failure: with reduced motion on the panel moves (${JSON.stringify(panelMotion)})`);
  document.querySelector<HTMLButtonElement>('footer.status-bar button[aria-label="Commands"]')!.click();
  const palette = await context.element('[role="dialog"][aria-label="Commands"]');
  const paletteMotion = motionOf(palette);
  expect(still(palette), `product-failure: with reduced motion on the palette moves (${JSON.stringify(paletteMotion)})`);
  return { outcome: "verified", phase: "on", matchMedia: reported, marked, panel: panelMotion, palette: paletteMotion };
};
