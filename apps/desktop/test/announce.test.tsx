/**
 * T047: what a screen reader is told, once; names for every region and
 * control; and the reduced-motion preference (FR-020).
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { click, render, type Rendered, typeInto, until } from "./render.ts";
import { openPalette, options, paletteInput, showSurface } from "./shell-helpers.ts";

let rendered: Rendered | undefined;
const realMatchMedia = window.matchMedia;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
  window.matchMedia = realMatchMedia;
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

function announcer(container: HTMLElement): HTMLElement {
  return container.querySelector<HTMLElement>('footer.status-bar [role="status"]')!;
}

/** Every text the region took, in order, from now on. */
function said(region: HTMLElement): string[] {
  const texts: string[] = [];
  new MutationObserver(() => texts.push(region.textContent ?? ""))
    .observe(region, { childList: true, characterData: true, subtree: true });
  return texts;
}

describe("announcements", () => {
  test("a change of the Core's state is said once", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    const region = announcer(container);
    await until(() => region.textContent === "Core: Ready", "ready said");
    const texts = said(region);
    native.push(status({ state: "restarting", restart_count: 1, core: null }));
    await until(() => region.textContent === "Core: Restarting…", "restarting said");
    native.push(status({ state: "restarting", restart_count: 1, core: null }));
    await until(() => container.querySelector('[data-testid="status-strip"][data-state="restarting"]'), "still");
    expect(texts.filter((text) => text === "Core: Restarting…").length).toBe(1);
  });

  test("a panel opening is said by its name", async () => {
    const { container } = await openWindow(show, until);
    await showSurface(container, "Diagnostics");
    await until(() => announcer(container).textContent === "Diagnostics panel opened", "said");
  });

  test("the palette's result count is said, and follows the query", async () => {
    const { container } = await openWindow(show, until);
    await openPalette(container);
    await until(() => announcer(container).textContent === `${options(container).length} commands`, "the count");
    await typeInto(paletteInput(container), "diagnostics");
    await until(() => announcer(container).textContent === `${options(container).length} ${
      options(container).length === 1 ? "command" : "commands"}`, "the narrowed count");
  });
});

describe("names", () => {
  test("every region and every control has an accessible name", async () => {
    const { container } = await openWindow(show, until);
    await showSurface(container, "Core");
    await until(() => container.querySelector('[role="dialog"].modal-panel'), "the panel");
    await openPalette(container);
    const shell = container.querySelector('[data-testid="shell"]')!;
    expect([...shell.querySelectorAll("nav")].map((nav) => nav.getAttribute("aria-label")))
      .toEqual(["Menu", "Workbench", "Mode"]);
    expect(shell.querySelector('[role="dialog"].modal-panel')!.getAttribute("aria-label")).toBe("Core");
    expect(shell.querySelector('[role="dialog"]')!.getAttribute("aria-label")).toBe("Commands");
    expect(shell.querySelector('[role="listbox"]')!.getAttribute("aria-label")).toBe("Commands");
    for (const control of shell.querySelectorAll<HTMLElement>("button, input, textarea, [role='option']")) {
      const name = control.getAttribute("aria-label") ?? control.textContent ?? "";
      expect([control.outerHTML.slice(0, 80), name.trim().length > 0]).toEqual([control.outerHTML.slice(0, 80), true]);
    }
  });
});

describe("reduced motion", () => {
  test("the shell marks itself when the system asks for reduced motion", async () => {
    window.matchMedia = ((query: string) => ({
      matches: query.includes("prefers-reduced-motion: reduce"), media: query, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
    const { container } = await openWindow(show, until);
    expect(container.querySelector('[data-testid="shell"]')!.getAttribute("data-reduced-motion")).toBe("true");
  });

  test("and does not otherwise", async () => {
    window.matchMedia = ((query: string) => ({
      matches: false, media: query, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
    const { container } = await openWindow(show, until);
    expect(container.querySelector('[data-testid="shell"]')!.getAttribute("data-reduced-motion")).toBe("false");
  });
});
