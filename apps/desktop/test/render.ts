/**
 * Rendering the window into happy-dom, and waiting on the DOM it produces.
 * No timers: a wait re-checks on every DOM change and every settled promise,
 * and gives up after a bounded number of turns rather than after a delay.
 */

import { act, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";

export interface Rendered {
  readonly container: HTMLElement;
  text(): string;
  unmount(): Promise<void>;
}

export async function render(element: ReactElement): Promise<Rendered> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  let root: Root | undefined;
  await act(async () => {
    root = createRoot(container);
    root.render(element);
  });
  return {
    container,
    text: () => container.textContent ?? "",
    unmount: async () => {
      await act(async () => root?.unmount());
      container.remove();
    },
  };
}

/** How many settled turns a wait may take before the test fails. */
const TURN_LIMIT = 500;

/** Let pending promises and React updates settle until `found` holds. */
export async function until<T>(found: () => T | null | undefined | false,
                               what = "the expected state"): Promise<T> {
  for (let turn = 0; turn < TURN_LIMIT; turn += 1) {
    const value = found();
    if (value) return value;
    await act(async () => {
      await Promise.resolve();
    });
  }
  throw new Error(`never reached ${what}`);
}

export async function click(element: Element): Promise<void> {
  await act(async () => {
    (element as HTMLElement).click();
  });
}

export function byText(container: HTMLElement, selector: string, text: string): HTMLElement | null {
  return [...container.querySelectorAll<HTMLElement>(selector)]
    .find((element) => (element.textContent ?? "").includes(text)) ?? null;
}
