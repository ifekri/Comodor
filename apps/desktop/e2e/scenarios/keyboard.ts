/**
 * D2 T050: the keyboard in the real WebView (US3; FR-018, FR-019, FR-034).
 * Keys here are dispatched in the page: this proves the shell's handling in
 * the real WebView, not that the operating system delivers a key — that is
 * the `key-delivery` scenario's evidence.
 */

import { expect, type Scenario, type ScenarioContext } from "../runner.ts";
import { panel, paletteControl, region, SIDEBAR } from "./workbench.ts";

const MAC = /Mac/i.test(navigator.userAgent);

function press(key: string, modifiers: { mod?: boolean; shift?: boolean } = {}): void {
  const target = document.activeElement ?? document.body;
  target.dispatchEvent(new KeyboardEvent("keydown", {
    key, bubbles: true, cancelable: true, shiftKey: modifiers.shift ?? false,
    ctrlKey: (modifiers.mod ?? false) && !MAC, metaKey: (modifiers.mod ?? false) && MAC,
  }));
}

/** The focus token's colour, as the browser computes `outline-color` from it. */
function tokenColour(): string {
  const probe = document.createElement("span");
  probe.style.color = "var(--border-focused)";
  document.body.appendChild(probe);
  const colour = getComputedStyle(probe).color;
  probe.remove();
  return colour;
}

/** The focused element draws a visible ring in the focus token's colour. */
function ringVisible(where: string): void {
  const active = document.activeElement as HTMLElement | null;
  expect(active !== null && active !== document.body, `${where}: something has focus`);
  const style = getComputedStyle(active!);
  expect(style.outlineStyle !== "none" && parseFloat(style.outlineWidth) >= 1,
         `${where}: a visible outline on ${active!.outerHTML.slice(0, 80)} (${style.outlineStyle} ${style.outlineWidth})`);
  expect(style.outlineColor === tokenColour(), `${where}: the focus token colour (${style.outlineColor})`);
}

async function settled(context: ScenarioContext, check: () => boolean): Promise<void> {
  await context.waitFor(() => check());
}

export const keyboard: Scenario = async (context) => {
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  await context.waitFor(() => document.querySelector('[data-testid="session"]'));
  const regions: (string | null)[] = [];

  // F6 around the regions, focus visible at each stop.
  paletteControl()!.focus();
  regions.push(region());
  ringVisible("top");
  const around = document.querySelector(SIDEBAR) === null ? ["main", "status", "top"] : ["sidebar", "main", "status", "top"];
  for (const expected of around) {
    press("F6");
    await settled(context, () => region() === expected);
    ringVisible(expected);
    regions.push(region());
  }
  press("F6", { shift: true });
  await settled(context, () => region() === "status");

  // The palette by its key; Escape gives focus back.
  const before = document.activeElement;
  press("k", { mod: true });
  const input = await context.element('[role="dialog"][aria-label="Commands"] [role="combobox"]');
  expect(document.activeElement === input, "the palette's input has focus");
  ringVisible("palette");
  press("Escape");
  await settled(context, () => document.querySelector('[role="dialog"]') === null);
  expect(document.activeElement === before, "focus came back to where it was");

  // A panel by its key; focus goes in, and back out when it closes.
  press("2", { mod: true });
  await settled(context, () => region() === "panel");
  ringVisible("panel");
  press("F6");
  await settled(context, () => region() === "status");
  press("2", { mod: true });
  await settled(context, () => panel() === null);
  return { regions, modality: "dispatched in the page" };
};
