/**
 * T045, corrected 2026-10-17: focus in the shell (FR-018, FR-019, FR-026,
 * SC-005) — Tab order, the F6 region cycle over the reference's regions,
 * focus into and back out of the panel, the palette and the covering
 * sidebar, and Escape's precedence: the palette, the panel, the covering
 * sidebar, then the composer.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FocusReturn } from "../src/shell/focus.ts";
import { FakeNative, openWindow } from "./fake-native.ts";
import { byText, click, render, type Rendered, typeInto, until } from "./render.ts";
import { diagnosticsCell, key, menuTrigger, palette, paletteControl, paletteInput, panelOf, resizeTo, showSurface,
         WIDE } from "./shell-helpers.ts";

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
  if (element.closest("header.top-bar")) return "top";
  if (element.closest('nav[aria-label="Workbench"]')) return "sidebar";
  if (element.closest("main")) return "main";
  if (element.closest('[role="dialog"].modal-panel')) return "panel";
  if (element.closest("footer.status-bar")) return "status";
  return null;
}

const panel = (container: HTMLElement) => container.querySelector('[role="dialog"].modal-panel');
const toggle = (container: HTMLElement) => container.querySelector<HTMLButtonElement>("button.sidebar-toggle")!;
const sidebar = (container: HTMLElement) => container.querySelector('nav[aria-label="Workbench"]');

async function compact(container: HTMLElement): Promise<void> {
  await resizeTo(800);
  await until(() => container.querySelector('[data-testid="shell"]')?.getAttribute("data-mode") === "covering",
              "covering mode");
}

describe("Tab order", () => {
  test("follows the regions in document order, with no positive tabindex and no Tab intercepted", async () => {
    const { container } = await openWindow(show, until);
    await showSurface(container, "Core");
    await until(() => panel(container), "the panel");
    const shell = container.querySelector('[data-testid="shell"]')!;
    const order = [...shell.children].map((child) => (child.classList.contains("canvas") ? "canvas"
      : child.classList.contains("modal-layer") ? "panel" : child.tagName.toLowerCase())).filter((tag) => tag !== "div");
    expect(order).toEqual(["header", "nav", "canvas", "footer", "panel"]);
    // Drawn over the canvas, but not modal: nothing traps focus (FR-018).
    expect(panel(container)!.hasAttribute("aria-modal")).toBe(false);
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
  test("cycles top bar → sidebar → main → panel → status bar → top bar, and Shift+F6 goes back", async () => {
    const { container } = await openWindow(show, until);
    await showSurface(container, "Core");
    await until(() => panel(container), "the panel");
    paletteControl(container).focus();
    const seen: (string | null)[] = [regionOf(document.activeElement)];
    for (let press = 0; press < 5; press += 1) {
      await key("F6");
      seen.push(regionOf(document.activeElement));
    }
    expect(seen).toEqual(["top", "sidebar", "main", "panel", "status", "top"]);
    await key("F6", { shiftKey: true });
    expect(regionOf(document.activeElement)).toBe("status");
  });

  test("skips the panel when it is closed", async () => {
    const { container } = await openWindow(show, until);
    paletteControl(container).focus();
    const seen: (string | null)[] = [];
    for (let press = 0; press < 4; press += 1) {
      await key("F6");
      seen.push(regionOf(document.activeElement));
    }
    expect(seen).toEqual(["sidebar", "main", "status", "top"]);
  });

  test("skips the sidebar when it is hidden", async () => {
    const { container } = await openWindow(show, until);
    await compact(container);
    paletteControl(container).focus();
    const seen: (string | null)[] = [];
    for (let press = 0; press < 3; press += 1) {
      await key("F6");
      seen.push(regionOf(document.activeElement));
    }
    expect(seen).toEqual(["main", "status", "top"]);
  });

  test("reaches the shell from a text field", async () => {
    const { container } = await openWindow(show, until);
    container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!.focus();
    await key("F6");
    expect(regionOf(document.activeElement)).toBe("status");
  });
});

describe("opening and closing", () => {
  test("the panel takes focus, and gives it back to the menu that opened it", async () => {
    const { container } = await openWindow(show, until);
    await showSurface(container, "Core");
    await until(() => panelOf(container, "Core"), "the panel");
    expect(regionOf(document.activeElement)).toBe("panel");
    await key("Escape");
    await until(() => panel(container) === null, "closed");
    expect(document.activeElement).toBe(menuTrigger(container, "Option"));
  });

  test("the panel gives focus back to the status bar cell that opened it, by its Close", async () => {
    const { container } = await openWindow(show, until);
    const cell = diagnosticsCell(container);
    cell.focus();
    await click(cell);
    await until(() => panelOf(container, "Diagnostics"), "the panel");
    expect(regionOf(document.activeElement)).toBe("panel");
    await click(byText(container, '[role="dialog"].modal-panel button', "Close")!);
    await until(() => panel(container) === null, "closed");
    expect(document.activeElement).toBe(diagnosticsCell(container));
  });

  test("a click on the backdrop closes the panel", async () => {
    const { container } = await openWindow(show, until);
    await showSurface(container, "Core");
    await until(() => panel(container), "the panel");
    await click(container.querySelector<HTMLElement>('[data-testid="panel-backdrop"]')!);
    await until(() => panel(container) === null, "closed");
  });

  test("below 900 px the sidebar covers the canvas, takes focus, and gives it back to its toggle", async () => {
    const { container } = await openWindow(show, until);
    await compact(container);
    expect(sidebar(container)).toBeNull();
    toggle(container).focus();
    await click(toggle(container));
    await until(() => container.querySelector("nav.sidebar-covering"), "the covering sidebar");
    await until(() => regionOf(document.activeElement) === "sidebar", "focus in the sidebar");
    await key("Escape");
    await until(() => sidebar(container) === null, "hidden again");
    expect(document.activeElement).toBe(toggle(container));
    await click(toggle(container));
    await until(() => container.querySelector("nav.sidebar-covering"), "covering again");
    await click(container.querySelector<HTMLElement>('[data-testid="sidebar-backdrop"]')!);
    await until(() => sidebar(container) === null, "closed by a click outside");
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
  test("closes the palette, then the panel, then the covering sidebar, then cancels in the composer — one per press", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    native.core.emit("session.updated", { session: { ...native.core.session, busy: true } });
    await until(() => byText(container, '[data-testid="composer"] button', "Cancel"), "Cancel");
    await compact(container);
    await click(toggle(container));
    await until(() => container.querySelector("nav.sidebar-covering"), "the covering sidebar");
    await click(diagnosticsCell(container));
    await until(() => panelOf(container, "Diagnostics"), "the panel over it");
    await key("k", { ctrlKey: true });
    await until(() => palette(container), "the palette over both");

    await key("Escape", {}, paletteInput(container));
    await until(() => palette(container) === null, "the palette closed");
    expect(panel(container)).not.toBeNull();
    expect(container.querySelector("nav.sidebar-covering")).not.toBeNull();

    await key("Escape");
    await until(() => panel(container) === null, "the panel closed");
    expect(container.querySelector("nav.sidebar-covering")).not.toBeNull();

    await key("Escape");
    await until(() => sidebar(container) === null, "the sidebar closed");
    expect(native.core.requests("session.cancel").length).toBe(0);

    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    field.focus();
    await key("Escape", {}, field);
    await until(() => native.core.requests("session.cancel").length === 1, "one cancel");
    expect(native.core.requests("session.cancel").length).toBe(1);
  });

  test("the panel and the covering sidebar each give focus back to their own opener, whichever closes first", async () => {
    const { container } = await openWindow(show, until);
    await compact(container);
    const cell = diagnosticsCell(container);
    cell.focus();
    await click(cell);
    await until(() => panelOf(container, "Diagnostics"), "the panel");
    // Opened from inside the panel: the covering sidebar's opener is in the panel.
    await key("b", { ctrlKey: true }, document.activeElement);
    await until(() => container.querySelector("nav.sidebar-covering"), "the covering sidebar");
    await key("Escape");
    await until(() => panel(container) === null, "the panel closed first");
    expect(document.activeElement).toBe(diagnosticsCell(container));
    await key("Escape");
    await until(() => sidebar(container) === null, "the sidebar closed");
    // Its opener went with the panel: the composer, as FR-019 says.
    expect(document.activeElement).toBe(container.querySelector('[data-testid="composer"] textarea'));
  });

  test("with the panel open, Escape in the composer cancels once (D1) and leaves the panel open", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    native.core.emit("session.updated", { session: { ...native.core.session, busy: true } });
    await until(() => byText(container, '[data-testid="composer"] button', "Cancel"), "Cancel");
    await showSurface(container, "Core");
    await until(() => panel(container), "the panel");
    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    field.focus();
    await key("Escape", {}, field);
    await until(() => native.core.requests("session.cancel").length === 1, "one cancel");
    expect(panel(container)).not.toBeNull();
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
