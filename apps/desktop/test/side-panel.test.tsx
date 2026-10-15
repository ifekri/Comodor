/**
 * T069: the side panel beside and covering, and its edge (FR-025, FR-026).
 */

import { act } from "react";
import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FakeNative, openWindow } from "./fake-native.ts";
import { click, render, type Rendered, until } from "./render.ts";
import { key, railButton, resizeTo, WIDE } from "./shell-helpers.ts";

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

function panel(container: HTMLElement): HTMLElement | null {
  return container.querySelector<HTMLElement>("aside");
}

function edge(container: HTMLElement): HTMLElement {
  return container.querySelector<HTMLElement>('aside [role="separator"]')!;
}

async function pointer(target: Element, type: string, clientX: number): Promise<void> {
  await act(async () => {
    target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX, button: 0 }));
  });
}

describe("beside and covering", () => {
  test("beside at 900 and above; covering below, closed by Escape and by a click outside", async () => {
    const { container } = await openWindow(show, until);
    await click(railButton(container, "Core"));
    await until(() => panel(container)?.classList.contains("side-panel-beside"), "beside");
    await resizeTo(899);
    await until(() => panel(container)?.classList.contains("side-panel-covering"), "covering below 900");
    await key("Escape", {}, panel(container));
    await until(() => panel(container) === null, "closed by Escape");
    await click(railButton(container, "Core"));
    await until(() => panel(container)?.classList.contains("side-panel-covering"), "covering again");
    await click(container.querySelector('[data-testid="panel-backdrop"]')!);
    await until(() => panel(container) === null, "closed by a click outside");
  });

  test("widening past 900 puts it back beside, at its remembered width", async () => {
    const native = new FakeNative();
    native.layoutAnswer = { layout: { version: 1, panel_open: true, panel_surface: "core", panel_width: 400 },
                            stored: true };
    const { container } = await openWindow(show, until, native);
    await until(() => panel(container)?.style.width === "400px", "400 beside");
    await resizeTo(700);
    await until(() => panel(container)?.classList.contains("side-panel-covering"), "covering");
    await resizeTo(1200);
    await until(() => panel(container)?.classList.contains("side-panel-beside"), "beside again");
    expect(panel(container)!.style.width).toBe("400px");
  });
});

describe("the edge", () => {
  test("is a focusable separator saying its width and range", async () => {
    const { container } = await openWindow(show, until);
    await click(railButton(container, "Core"));
    await until(() => panel(container), "the panel");
    const separator = edge(container);
    expect(separator.tabIndex).toBe(0);
    expect(separator.getAttribute("aria-orientation")).toBe("vertical");
    expect(separator.getAttribute("aria-label")).toBe("Resize the side panel");
    expect(separator.getAttribute("aria-valuenow")).toBe("320");
    expect(separator.getAttribute("aria-valuemin")).toBe("240");
    expect(separator.getAttribute("aria-valuemax")).toBe(String(Math.min(WIDE / 2, WIDE - 56 - 360)));
  });

  test("Left widens and Right narrows by 32; Home and End go to the ends; each step is written", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    await click(railButton(container, "Core"));
    await until(() => native.writtenLayouts.length === 1, "opened");
    const separator = edge(container);
    separator.focus();
    const width = () => Number(edge(container).getAttribute("aria-valuenow"));
    await key("ArrowLeft", {}, separator);
    await until(() => width() === 352, "wider");
    await key("ArrowRight", {}, separator);
    await until(() => width() === 320, "narrower");
    await key("Home", {}, separator);
    await until(() => width() === 240, "the minimum");
    await key("End", {}, separator);
    await until(() => width() === Number(edge(container).getAttribute("aria-valuemax")), "the maximum");
    expect(native.writtenLayouts.length).toBe(5);
  });

  test("arrow keys act on the edge only", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    await click(railButton(container, "Core"));
    await until(() => native.writtenLayouts.length === 1, "opened");
    for (const target of [document.body, railButton(container, "Core"),
                          container.querySelector('[data-testid="composer"] textarea')!]) {
      const event = await key("ArrowLeft", {}, target);
      expect(event.defaultPrevented).toBe(false);
    }
    expect(edge(container).getAttribute("aria-valuenow")).toBe("320");
    expect(native.writtenLayouts.length).toBe(1);
  });

  test("a drag resizes as it moves and writes once, when it ends", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    await click(railButton(container, "Core"));
    await until(() => native.writtenLayouts.length === 1, "opened");
    const separator = edge(container);
    await pointer(separator, "pointerdown", 700);
    await pointer(window as unknown as Element, "pointermove", 680);
    await pointer(window as unknown as Element, "pointermove", 650);
    await until(() => panel(container)?.style.width === "370px", "370 while dragging");
    expect(native.writtenLayouts.length).toBe(1);
    await pointer(window as unknown as Element, "pointerup", 650);
    await until(() => native.writtenLayouts.length === 2, "written once");
    expect((native.writtenLayouts[1] as { panel_width: number }).panel_width).toBe(370);
  });
});
