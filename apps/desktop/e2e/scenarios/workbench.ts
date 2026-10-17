/**
 * D2's controls where the reference window places them (spec Clarifications,
 * 2026-10-17), for the real-WebView scenarios: the top bar's menus and
 * search, the sidebar, the panel drawn over the canvas.
 */

import type { ScenarioContext } from "../runner.ts";

export const SIDEBAR = 'nav[aria-label="Workbench"]';

/** The open panel, or the one showing `name`. */
export function panel(name?: string): HTMLElement | null {
  const label = name === undefined ? "" : `[aria-label="${name}"]`;
  return document.querySelector<HTMLElement>(`[role="dialog"].modal-panel${label}`);
}

/** The top bar's search: the palette's visible control (an icon when the menus fold). */
export function paletteControl(): HTMLButtonElement | null {
  return document.querySelector<HTMLButtonElement>('header.top-bar button[data-focus-key="palette-control"]');
}

/** The region holding focus: the top bar, the sidebar, main, the panel or the status bar. */
export function region(): string | null {
  const active = document.activeElement;
  if (!active) return null;
  if (active.closest("header.top-bar")) return "top";
  if (active.closest(SIDEBAR)) return "sidebar";
  if (active.closest("main")) return "main";
  if (active.closest('[role="dialog"].modal-panel')) return "panel";
  if (active.closest("footer.status-bar")) return "status";
  return null;
}

/**
 * Choose a menu's item as a person does with the pointer: the menu's own
 * trigger, or "Menu" when the menus are folded (below 760 px).
 */
export async function chooseMenuItem(context: ScenarioContext, menu: string, item: string): Promise<void> {
  const own = document.querySelector<HTMLButtonElement>(`header.top-bar button[data-menu="${menu}"]`);
  const trigger = own ?? document.querySelector<HTMLButtonElement>('header.top-bar button[data-menu="Menu"]');
  if (trigger === null) throw new Error(`neither the ${menu} menu nor "Menu" is in the top bar`);
  const shown = own === null ? `${menu} · ${item}` : item;
  trigger.click();
  const found = await context.waitFor(() => [...document.querySelectorAll<HTMLButtonElement>(
    `[data-menu-of="${trigger.getAttribute("data-menu")}"] [role="menuitem"]`)]
    .find((button) => button.querySelector(".menu-label")?.textContent === shown));
  found.click();
}

const SURFACE_ITEMS: Readonly<Record<string, string>> = {
  Core: "Core", Diagnostics: "Diagnostics", "Keyboard shortcuts": "Keyboard Shortcuts",
};

/** Show a surface in the panel from the Option menu, and wait for it. */
export async function showSurface(context: ScenarioContext, name: string): Promise<HTMLElement> {
  await chooseMenuItem(context, "Option", SURFACE_ITEMS[name] ?? name);
  return await context.waitFor(() => panel(name));
}
