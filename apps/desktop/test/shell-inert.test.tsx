/**
 * T073: text from outside the application is inert in every D2 surface
 * (FR-032), and right-to-left text shows in its own direction while the
 * layout itself does not mirror (edge cases).
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { click, render, type Rendered, until } from "./render.ts";
import { showSurface } from "./shell-helpers.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

const HOSTILE = "مدل-۱ <script>alert(1)</script><img src=x onerror=alert(1)> \x1b[2J\x1b[H\x1b]0;owned\x07 "
  + "javascript:alert(1) [Connected] [Ready]";
const PERSIAN = "/work/دفتر پروژه/src";

describe("hostile text from the Core", () => {
  test("is inert in the status bar and the Core panel", async () => {
    const native = new FakeNative(status({ workspace: PERSIAN }));
    native.core.session = { ...native.core.session, workspace: PERSIAN };
    native.core.model = { provider: HOSTILE, model: HOSTILE, configured: true };
    const { container } = await openWindow(show, until, native);
    await showSurface(container, "Core");
    const panel = await until(() => container.querySelector<HTMLElement>('[role="dialog"][aria-label="Core"]'), "the panel");
    await until(() => (panel.textContent ?? "").includes("مدل-۱"), "the model in the panel");
    const bar = container.querySelector<HTMLElement>("footer.status-bar")!;
    await until(() => (bar.textContent ?? "").includes("مدل-۱"), "the model in the status bar");
    for (const region of [panel, bar]) {
      expect(region.querySelector("script, img, iframe, object, embed, a, button.link")).toBeNull();
      expect(region.textContent).not.toContain("\x1b");
      expect(region.textContent).toContain("<script>alert(1)</script>");
      expect(region.textContent).toContain("␛[2J␛[H");
    }
    expect(container.querySelector(".status-state")!.textContent).toBe("Ready");
    expect(container.querySelectorAll('[data-testid="status-strip"]').length).toBe(1);
    expect(document.title).not.toBe("owned");
  });
});

describe("right-to-left text", () => {
  test("shows in its own direction, and the layout does not mirror", async () => {
    const native = new FakeNative(status({ workspace: PERSIAN }));
    native.core.session = { ...native.core.session, workspace: PERSIAN };
    const { container } = await openWindow(show, until, native);
    await showSurface(container, "Core");
    const panel = await until(() => container.querySelector<HTMLElement>('[role="dialog"][aria-label="Core"]'), "the panel");
    await until(() => (panel.textContent ?? "").includes("دفتر پروژه"), "the Persian path");
    for (const value of panel.querySelectorAll("dd")) expect(value.getAttribute("dir")).toBe("auto");
    const shell = container.querySelector('[data-testid="shell"]')!;
    expect(shell.getAttribute("dir")).toBeNull();
    expect(document.documentElement.getAttribute("dir")).not.toBe("rtl");
    // The reference's left-to-right order holds: top bar, the sidebar on the left, the canvas, the status bar.
    const order = [...shell.children]
      .map((child) => (child.classList.contains("canvas") ? "canvas" : child.tagName.toLowerCase()))
      .filter((tag) => tag !== "div");
    expect(order).toEqual(["header", "nav", "canvas", "footer"]);
  });
});

describe("the diagnostics panel", () => {
  test("shows hostile and right-to-left output inertly, in its own direction", async () => {
    const native = new FakeNative();
    native.diagnostics = `${HOSTILE}\nخطا در ${PERSIAN}`;
    const { container } = await openWindow(show, until, native);
    await showSurface(container, "Diagnostics");
    const panel = await until(() => container.querySelector<HTMLElement>('[role="dialog"][aria-label="Diagnostics"]'), "the panel");
    const tail = await until(() => panel.querySelector<HTMLElement>('[data-testid="diagnostics-tail"]'), "the tail");
    expect(panel.querySelector("script, img, iframe, object, embed, a, button.link")).toBeNull();
    expect(tail.textContent).not.toContain("\x1b");
    expect(tail.textContent).toContain("<script>alert(1)</script>");
    expect(tail.textContent).toContain("␛[2J␛[H");
    expect(tail.textContent).toContain("دفتر پروژه");
    expect(tail.getAttribute("dir")).toBe("auto");
    expect(container.querySelector('[data-testid="shell"]')!.getAttribute("dir")).toBeNull();
    expect(document.title).not.toBe("owned");
  });
});
