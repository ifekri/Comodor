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

export function railButton(container: HTMLElement, name: string): HTMLButtonElement {
  return [...container.querySelectorAll<HTMLButtonElement>('nav[aria-label="Workbench"] button')]
    .find((button) => button.getAttribute("aria-label") === name)!;
}

/** Open the palette with the status bar's control, and wait for it. */
export async function openPalette(container: HTMLElement): Promise<HTMLElement> {
  await click(container.querySelector('footer.status-bar button[aria-label="Commands"]')!);
  return await until(() => palette(container), "the palette");
}

/** The window's width, as a person resizes it (happy-dom has no layout: the shell falls back to it). */
export async function resizeTo(width: number): Promise<void> {
  await act(async () => {
    (window as unknown as { happyDOM: { setInnerWidth(width: number): void } }).happyDOM.setInnerWidth(width);
    window.dispatchEvent(new Event("resize"));
  });
}

/** The default width of the window tests: wide enough for the panel beside the main area. */
export const WIDE = 1024;
