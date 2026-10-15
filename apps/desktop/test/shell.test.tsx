/**
 * T026: the workbench shell around D1's window (US1; FR-001, FR-003, FR-004,
 * FR-006, FR-007), against the in-memory native side and Core.
 */

import { afterEach, describe, expect, test } from "bun:test";

import type { CoreStatus } from "../src/bridge.ts";
import { App } from "../src/app.tsx";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { click, render, type Rendered, until } from "./render.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

const STATES: Record<string, Partial<CoreStatus>> = {
  ready: {},
  starting: { state: "starting", core: null },
  handshaking: { state: "handshaking", core: null },
  checking: { state: "checking", check_epoch: 1 },
  restarting: { state: "restarting", restart_count: 1, core: null },
  failed: { state: "failed", core: null, failure: { class: "crashed", message: "it stopped" } },
  stopping: { state: "stopping", closing: { seconds_remaining: 7 } },
  absent: { state: "absent", workspace: null, workspace_id: null, core: null, notice: null },
};

function rail(container: HTMLElement): HTMLElement | null {
  return container.querySelector<HTMLElement>('nav[aria-label="Workbench"]');
}

function railButton(container: HTMLElement, name: string): HTMLButtonElement {
  return [...rail(container)!.querySelectorAll<HTMLButtonElement>("button")]
    .find((button) => button.getAttribute("aria-label") === name || button.textContent?.trim() === name)!;
}

describe("the four regions", () => {
  for (const [name, overrides] of Object.entries(STATES)) {
    test(`are present in the ${name} state`, async () => {
      const view = await show(new FakeNative(status(overrides)));
      await until(() => view.container.querySelector('[data-testid="status-strip"]'), "the status strip");
      const container = view.container;
      expect(rail(container)).not.toBeNull();
      const mains = container.querySelectorAll("main");
      expect(mains.length).toBe(1);
      expect(mains[0]!.getAttribute("data-testid")).toBe("window");
      const bar = container.querySelector<HTMLElement>("footer.status-bar");
      expect(bar).not.toBeNull();
      expect(bar!.querySelector('[role="status"]')).not.toBeNull();
      expect(container.querySelectorAll('[data-testid="status-strip"]').length).toBe(1);
      expect(bar!.querySelector('[data-testid="status-strip"]')).not.toBeNull();
      expect(bar!.querySelector('button[aria-label="Commands"]')).not.toBeNull();
    });
  }

  test("D1's views sit in D1's main", async () => {
    for (const [name, testid] of [["failed", "failure-view"], ["stopping", "closing"],
                                  ["absent", "workspace-gate"]] as const) {
      const view = await show(new FakeNative(status(STATES[name])));
      const found = await until(() => view.container.querySelector(`[data-testid="${testid}"]`), testid);
      expect(found.closest("main")?.getAttribute("data-testid")).toBe("window");
      await rendered!.unmount();
      rendered = undefined;
    }
    const { container } = await openWindow(show, until);
    for (const testid of ["conversation", "composer", "mode"]) {
      expect(container.querySelector(`[data-testid="${testid}"]`)?.closest("main")?.getAttribute("data-testid"))
        .toBe("window");
    }
  });

  test("the status bar carries the Core's values as the strip did", async () => {
    const native = new FakeNative(status({ workspace: "/repo/src" }));
    native.core.session = { ...native.core.session, workspace: "/repo" };
    native.core.model = { provider: "fake", model: "fake-1", configured: true };
    const view = await show(native);
    const strip = await until(() =>
      view.container.querySelector<HTMLElement>('footer.status-bar [data-testid="status-strip"][data-state="ready"]'),
      "the strip in the status bar");
    await until(() => strip.textContent?.includes("fake-1"), "the model");
    await until(() => strip.querySelector(".status-workspace")?.textContent === "/repo", "the Core's workspace");
    expect(strip.querySelector(".status-state")?.textContent).toBe("Ready");
    expect(strip.textContent).toContain("Configured");
  });
});

describe("the rail", () => {
  test("lists exactly the four surfaces and the palette control, each named with an icon", async () => {
    const { container } = await openWindow(show, until);
    const buttons = [...rail(container)!.querySelectorAll<HTMLButtonElement>("button")];
    expect(buttons.map((button) => button.getAttribute("aria-label")))
      .toEqual(["Conversation", "Core", "Diagnostics", "Keyboard shortcuts", "Commands"]);
    for (const button of buttons) {
      const icon = button.querySelector('[aria-hidden="true"]');
      expect(icon).not.toBeNull();
      expect(button.getAttribute("title")).toBeTruthy();
    }
  });

  test("marks which surface is active", async () => {
    const { container } = await openWindow(show, until);
    expect(railButton(container, "Conversation").getAttribute("aria-current")).toBe("true");
    await click(railButton(container, "Core"));
    await until(() => container.querySelector('aside[aria-label="Core"]'), "the Core panel");
    expect(railButton(container, "Core").getAttribute("aria-current")).toBe("true");
    expect(railButton(container, "Diagnostics").getAttribute("aria-current")).toBe("false");
  });
});

describe("choosing a surface", () => {
  test("shows it in the side panel; choosing the one shown closes the panel", async () => {
    const { container } = await openWindow(show, until);
    expect(container.querySelector("aside")).toBeNull();
    await click(railButton(container, "Diagnostics"));
    await until(() => container.querySelector('aside[aria-label="Diagnostics"]'), "diagnostics");
    await click(railButton(container, "Keyboard shortcuts"));
    await until(() => container.querySelector('aside[aria-label="Keyboard shortcuts"]'), "the shortcuts");
    expect(container.querySelectorAll("aside").length).toBe(1);
    await click(railButton(container, "Keyboard shortcuts"));
    await until(() => container.querySelector("aside") === null, "the panel closed");
  });

  test("the conversation is the main area: choosing it moves focus there, beside an open panel", async () => {
    const { container } = await openWindow(show, until);
    await click(railButton(container, "Core"));
    await until(() => container.querySelector('aside[aria-label="Core"]'), "the Core panel");
    await click(railButton(container, "Conversation"));
    expect(container.querySelector('main [data-testid="conversation"]')).not.toBeNull();
    expect(document.activeElement?.closest("main")?.getAttribute("data-testid")).toBe("window");
    expect(container.querySelector('aside[aria-label="Core"]')).not.toBeNull();
    expect(railButton(container, "Core").getAttribute("aria-current")).toBe("true");
  });
});
