/**
 * T045: focus in the shell (FR-018, FR-019, SC-005) — Tab order, the F6
 * region cycle, focus into and back out of every overlay, and Escape's
 * precedence: palette, then a covering panel, then the composer.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FocusReturn } from "../src/shell/focus.ts";
import { FakeNative, openWindow } from "./fake-native.ts";
import { byText, click, render, type Rendered, typeInto, until } from "./render.ts";
import { key, palette, paletteInput, railButton, resizeTo, WIDE } from "./shell-helpers.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
  await resizeTo(WIDE);
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

function regionOf(element: Element | null): string | null {
  if (!element) return null;
  if (element.closest('nav[aria-label="Workbench"]')) return "rail";
  if (element.closest("main")) return "main";
  if (element.closest("aside")) return "panel";
  if (element.closest("footer.status-bar")) return "status";
  return null;
}

describe("Tab order", () => {
  test("follows the regions in document order, with no positive tabindex and no Tab intercepted", async () => {
    const { container } = await openWindow(show, until);
    await click(railButton(container, "Core"));
    await until(() => container.querySelector("aside"), "the panel");
    const shell = container.querySelector('[data-testid="shell"]')!;
    const order = [...shell.children].map((child) => child.tagName.toLowerCase()).filter((tag) => tag !== "div");
    expect(order).toEqual(["nav", "main", "aside", "footer"]);
    const positive = [...shell.querySelectorAll("[tabindex]")]
      .filter((element) => Number(element.getAttribute("tabindex")) > 0);
    expect(positive).toEqual([]);
    for (const element of shell.querySelectorAll<HTMLElement>("button, textarea, input")) {
      const tab = await key("Tab", {}, element);
      const back = await key("Tab", { shiftKey: true }, element);
      expect([tab.defaultPrevented, back.defaultPrevented]).toEqual([false, false]);
    }
  });
});

describe("F6", () => {
  test("cycles rail → main → side panel → status bar → rail, and Shift+F6 goes back", async () => {
    const { container } = await openWindow(show, until);
    await click(railButton(container, "Core"));
    await until(() => container.querySelector("aside"), "the panel");
    railButton(container, "Conversation").focus();
    const seen: (string | null)[] = [regionOf(document.activeElement)];
    for (let press = 0; press < 4; press += 1) {
      await key("F6");
      seen.push(regionOf(document.activeElement));
    }
    expect(seen).toEqual(["rail", "main", "panel", "status", "rail"]);
    await key("F6", { shiftKey: true });
    expect(regionOf(document.activeElement)).toBe("status");
  });

  test("skips the side panel when it is closed", async () => {
    const { container } = await openWindow(show, until);
    railButton(container, "Conversation").focus();
    const seen: (string | null)[] = [];
    for (let press = 0; press < 3; press += 1) {
      await key("F6");
      seen.push(regionOf(document.activeElement));
    }
    expect(seen).toEqual(["main", "status", "rail"]);
  });

  test("reaches the shell from a text field", async () => {
    const { container } = await openWindow(show, until);
    container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!.focus();
    await key("F6");
    expect(regionOf(document.activeElement)).toBe("status");
  });
});

describe("opening and closing", () => {
  test("a side panel takes focus, and gives it back to the rail button that opened it", async () => {
    const { container } = await openWindow(show, until);
    const core = railButton(container, "Core");
    core.focus();
    await click(core);
    await until(() => container.querySelector("aside"), "the panel");
    expect(regionOf(document.activeElement)).toBe("panel");
    await click(railButton(container, "Core"));
    await until(() => container.querySelector("aside") === null, "closed");
    expect(document.activeElement).toBe(railButton(container, "Core"));
  });

  test("the palette takes focus, and gives it back to the composer that had it", async () => {
    const { container } = await openWindow(show, until);
    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    field.focus();
    await key("k", { ctrlKey: true });
    await until(() => palette(container), "the palette");
    expect(document.activeElement).toBe(paletteInput(container));
    await key("Escape", {}, paletteInput(container));
    await until(() => palette(container) === null, "closed");
    expect(document.activeElement).toBe(field);
  });

  test("when the element that opened it is gone, focus goes to the composer, else to the main area", async () => {
    const { container } = await openWindow(show, until);
    const gone = document.createElement("button");
    container.appendChild(gone);
    const returns = new FocusReturn();
    returns.push(gone);
    gone.remove();
    returns.restore(container);
    expect(document.activeElement).toBe(container.querySelector('[data-testid="composer"] textarea'));

    const bare = document.createElement("div");
    const main = document.createElement("main");
    main.tabIndex = -1;
    bare.appendChild(main);
    document.body.appendChild(bare);
    returns.push(null);
    returns.restore(bare);
    expect(document.activeElement).toBe(main);
    bare.remove();
  });
});

describe("Escape", () => {
  test("closes the palette, then a covering panel, then cancels in the composer — one action per press", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    native.core.emit("session.updated", { session: { ...native.core.session, busy: true } });
    await until(() => byText(container, '[data-testid="composer"] button', "Cancel"), "Cancel");
    await resizeTo(800);
    await until(() => container.querySelector('[data-testid="shell"]')?.getAttribute("data-mode") === "covering",
                "covering mode");
    await click(railButton(container, "Diagnostics"));
    await until(() => container.querySelector('aside.side-panel-covering'), "the covering panel");
    await key("k", { ctrlKey: true });
    await until(() => palette(container), "the palette over it");

    await key("Escape", {}, paletteInput(container));
    await until(() => palette(container) === null, "the palette closed");
    expect(container.querySelector("aside")).not.toBeNull();
    expect(native.core.requests("session.cancel").length).toBe(0);

    await key("Escape");
    await until(() => container.querySelector("aside") === null, "the covering panel closed");
    expect(native.core.requests("session.cancel").length).toBe(0);

    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    field.focus();
    await key("Escape", {}, field);
    await until(() => native.core.requests("session.cancel").length === 1, "one cancel");
    expect(native.core.requests("session.cancel").length).toBe(1);
  });

  test("beside an open panel, Escape in the composer cancels once and leaves the panel open", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    native.core.emit("session.updated", { session: { ...native.core.session, busy: true } });
    await until(() => byText(container, '[data-testid="composer"] button', "Cancel"), "Cancel");
    await click(railButton(container, "Core"));
    await until(() => container.querySelector('aside.side-panel-beside'), "the panel beside");
    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    field.focus();
    await key("Escape", {}, field);
    await until(() => native.core.requests("session.cancel").length === 1, "one cancel");
    expect(container.querySelector("aside")).not.toBeNull();
  });

  test("Enter in the composer sends once", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    await typeInto(field, "only once");
    field.focus();
    await key("Enter", {}, field);
    await until(() => native.core.requests("session.send").length === 1, "one send");
    expect(native.core.requests("session.send").length).toBe(1);
  });
});
