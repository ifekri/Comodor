/**
 * T063: the diagnostics panel (US5; FR-009, FR-032): the native side's
 * diagnostic tail as inert text, fetched when it opens, on refresh and
 * whenever the Core fails, in every state.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { click, render, type Rendered, until } from "./render.ts";
import { openPalette, paletteInput, showSurface } from "./shell-helpers.ts";
import { typeInto } from "./render.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

const ADVERSARIAL = "Traceback\n\x1b[2J\x1b[H\x1b]0;owned\x07 <script>alert(1)</script> <img src=x onerror=alert(1)> "
  + "javascript:alert(1) https://example.com/x [Connected] [Ready]";

function tail(container: HTMLElement): HTMLElement | null {
  return container.querySelector<HTMLElement>('[role="dialog"][aria-label="Diagnostics"] [data-testid="diagnostics-tail"]');
}

describe("the tail", () => {
  test("is fetched when the panel opens, and shown as inert text", async () => {
    const native = new FakeNative();
    native.diagnostics = ADVERSARIAL;
    const { container } = await openWindow(show, until, native);
    const before = native.commands("diagnostics").length;
    await showSurface(container, "Diagnostics");
    const shown = await until(() => tail(container)?.textContent?.includes("Traceback") && tail(container), "the tail");
    expect(native.commands("diagnostics").length).toBe(before + 1);
    const panel = container.querySelector<HTMLElement>('[role="dialog"][aria-label="Diagnostics"]')!;
    expect(panel.querySelector("script, img, iframe, object, embed, a")).toBeNull();
    expect(panel.querySelector("button.link")).toBeNull();
    expect(shown.textContent).not.toContain("\x1b");
    expect(shown.textContent).toContain("␛[2J␛[H");
    expect(shown.textContent).toContain("<script>alert(1)</script>");
    expect(shown.textContent).toContain("[Connected] [Ready]");
    expect(container.querySelector('[data-testid="status-strip"]')!.getAttribute("data-state")).toBe("ready");
    expect(document.title).not.toBe("owned");
  });

  test("is fetched again on refresh", async () => {
    const native = new FakeNative();
    native.diagnostics = "first";
    const { container } = await openWindow(show, until, native);
    await showSurface(container, "Diagnostics");
    await until(() => tail(container)?.textContent === "first", "the first tail");
    native.diagnostics = "second";
    await openPalette(container);
    await typeInto(paletteInput(container), "refresh");
    await click(await until(() => container.querySelector('[role="option"][data-command="diagnostics.refresh"]'),
                            "Refresh diagnostics"));
    await until(() => tail(container)?.textContent === "second", "the second tail");
  });

  test("is fetched again whenever the Core fails", async () => {
    const native = new FakeNative();
    native.diagnostics = "before";
    const { container } = await openWindow(show, until, native);
    await showSurface(container, "Diagnostics");
    await until(() => tail(container)?.textContent === "before", "the tail");
    native.diagnostics = "after the failure";
    native.push(status({ state: "failed", core: null, failure: { class: "crashed", message: "x" } }));
    await until(() => tail(container)?.textContent === "after the failure", "the tail after the failure");
  });

  test("is available in every state, not only on failure", async () => {
    for (const overrides of [{ state: "starting" as const, core: null }, { state: "stopping" as const,
                             closing: { seconds_remaining: 3 } }]) {
      const native = new FakeNative(status(overrides));
      native.diagnostics = `tail while ${overrides.state}`;
      const view = await show(native);
      await until(() => view.container.querySelector('[data-testid="status-strip"]'), "the strip");
      await showSurface(view.container, "Diagnostics");
      await until(() => tail(view.container)?.textContent === `tail while ${overrides.state}`, overrides.state);
      await rendered!.unmount();
      rendered = undefined;
    }
  });
});
