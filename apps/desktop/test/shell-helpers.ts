/**
 * Helpers for D2's shell tests: keys with every modifier, the palette's
 * options, and the rail. Window tests run on a "Linux" user agent, so the
 * primary modifier is Control.
 */

import { act } from "react";

import { click, until } from "./render.ts";

export interface Modifiers {
  shiftKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  metaKey?: boolean;
}

/** A key as a person presses it, on `target` (the focused element by default). */
export async function key(name: string, modifiers: Modifiers = {},
                          target: Element | null = document.activeElement): Promise<KeyboardEvent> {
  const event = new KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true, ...modifiers });
  await act(async () => {
    (target ?? document.body).dispatchEvent(event);
  });
  return event;
}

export function palette(container: HTMLElement): HTMLElement | null {
  return container.querySelector<HTMLElement>('[role="dialog"][aria-label="Commands"]');
}

export function paletteInput(container: HTMLElement): HTMLInputElement {
  return palette(container)!.querySelector<HTMLInputElement>('[role="combobox"]')!;
}

export function options(container: HTMLElement): HTMLElement[] {
  return [...(palette(container)?.querySelectorAll<HTMLElement>('[role="option"]') ?? [])];
}

export function optionIds(container: HTMLElement): string[] {
  return options(container).map((option) => option.getAttribute("data-command") ?? "");
}

export function highlighted(container: HTMLElement): string | null {
  return options(container).find((option) => option.getAttribute("aria-selected") === "true")
    ?.getAttribute("data-command") ?? null;
}

/** A top-bar menu's trigger ("File", "Option", … or "Menu" when folded). */
export function menuTrigger(container: HTMLElement, label: string): HTMLButtonElement {
  return container.querySelector<HTMLButtonElement>(`header.top-bar button[data-menu="${label}"]`)!;
}

/** Open a menu and choose one of its items, as a person does with the mouse. */
export async function chooseMenuItem(container: HTMLElement, menu: string, item: string): Promise<HTMLButtonElement> {
  await click(menuTrigger(container, menu));
  const found = await until(() => [...container.querySelectorAll<HTMLButtonElement>(`[data-menu-of="${menu}"] [role="menuitem"]`)]
    .find((button) => button.querySelector(".menu-label")?.textContent === item), `the ${item} item`);
  await click(found);
  return found;
}

/** The menu item that shows each surface (Option menu), by the surface's name. */
const SURFACE_ITEMS: Readonly<Record<string, string>> = {
  Core: "Core", Diagnostics: "Diagnostics", "Keyboard shortcuts": "Keyboard Shortcuts",
};

/** Show a surface from the Option menu (the reference's place for the window's panels). */
export async function showSurface(container: HTMLElement, name: string): Promise<void> {
  await chooseMenuItem(container, "Option", SURFACE_ITEMS[name] ?? name);
}

/** The modal panel of a surface, if it is open. */
export function panelOf(container: HTMLElement, name: string): HTMLElement | null {
  return container.querySelector<HTMLElement>(`[role="dialog"][aria-label="${name}"]`);
}

/** The status bar's Diagnostics cell: one click, as the rail button was. */
export function diagnosticsCell(container: HTMLElement): HTMLButtonElement {
  return container.querySelector<HTMLButtonElement>("footer.status-bar .status-diagnostics")!;
}

/** The top bar's search: the palette's visible control. */
export function paletteControl(container: HTMLElement): HTMLButtonElement {
  return container.querySelector<HTMLButtonElement>('header.top-bar button[aria-label="Commands"]')!;
}

/** Open the palette with the top bar's search, and wait for it. */
export async function openPalette(container: HTMLElement): Promise<HTMLElement> {
  await click(paletteControl(container));
  return await until(() => palette(container), "the palette");
}

/** The window's width, as a person resizes it (happy-dom has no layout: the shell falls back to it). */
export async function resizeTo(width: number): Promise<void> {
  await act(async () => {
    (window as unknown as { happyDOM: { setInnerWidth(width: number): void } }).happyDOM.setInnerWidth(width);
    window.dispatchEvent(new Event("resize"));
  });
}

/** The default width of the window tests: wide enough for the sidebar beside the canvas. */
export const WIDE = 1024;
