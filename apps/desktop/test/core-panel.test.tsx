/**
 * T062: the Core panel shows only what was reported for the current Core
 * (US5; FR-008, FR-010, FR-028, SC-010).
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FakeCore } from "./fake-core.ts";
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

const NOT_REPORTED = "not reported yet";

/** The panel's values, by their label. */
function values(container: HTMLElement): Record<string, string> {
  const panel = container.querySelector<HTMLElement>('[role="dialog"][aria-label="Core"]');
  const shown: Record<string, string> = {};
  for (const term of panel?.querySelectorAll("dt") ?? []) {
    shown[term.textContent ?? ""] = (term.nextElementSibling?.textContent ?? "").trim();
  }
  return shown;
}

async function openCore(container: HTMLElement): Promise<void> {
  await showSurface(container, "Core");
  await until(() => container.querySelector('[role="dialog"][aria-label="Core"]'), "the Core panel");
}

describe("the values", () => {
  test("are exactly as the native side, the handshake and the Core reported them", async () => {
    const native = new FakeNative(status({ workspace: "/repo/src", restart_count: 1, restart_limit: 3 }));
    native.core.session = { ...native.core.session, workspace: "/repo" };
    native.core.model = { provider: "fake", model: "fake-1", configured: true };
    const { container } = await openWindow(show, until, native);
    await openCore(container);
    await until(() => values(container)["Model"] === "fake-1", "the model");
    await until(() => values(container)["Workspace"] === "/repo", "the Core's workspace");
    expect(values(container)).toEqual({
      State: "Ready",
      Workspace: "/repo",
      Core: "comodor-core test",
      "Protocol version": "2",
      Provider: "fake",
      Model: "fake-1",
      Configured: "Yes",
      Restarts: "1 of 3",
    });
  });

  test("a value not reported yet says so, never a guess", async () => {
    const native = new FakeNative(status({ state: "starting", core: null }));
    const view = await show(native);
    await until(() => view.container.querySelector('[data-testid="status-strip"]'), "the strip");
    await openCore(view.container);
    const shown = values(view.container);
    expect(shown["State"]).toBe("Starting…");
    for (const label of ["Core", "Protocol version", "Provider", "Model", "Configured"]) {
      expect([label, shown[label]]).toEqual([label, NOT_REPORTED]);
    }
    expect(shown["Workspace"]).toBe("/work/project");
    expect(shown["Failure"]).toBeUndefined();
  });

  test("the failure is shown only when the Core failed", async () => {
    const native = new FakeNative(status({ state: "failed", core: null,
                                           failure: { class: "crashed", message: "it stopped" } }));
    const view = await show(native);
    await until(() => view.container.querySelector('[data-testid="failure-view"]'), "failed");
    await openCore(view.container);
    expect(values(view.container)["Failure"]).toContain("it stopped");
  });

  test("a long value is truncated on screen and whole on focus and hover", async () => {
    const long = `/work/${"a-very-long-folder-name/".repeat(8)}end`;
    const native = new FakeNative(status({ workspace: long }));
    native.core.session = { ...native.core.session, workspace: long };
    const { container } = await openWindow(show, until, native);
    await openCore(container);
    const value = await until(() => container.querySelector<HTMLElement>(`.modal-panel [title="${long}"]`), "the whole value");
    expect(value.tabIndex).toBe(0);
    expect(value.classList.contains("core-value")).toBe(true);
  });
});

describe("clearing", () => {
  test("a Core restart clears every value until the new Core reports it", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    await openCore(container);
    await until(() => values(container)["Model"] === "fake-1", "the first Core's model");
    const next = new FakeCore();
    next.model = { provider: "fake", model: "fake-2", configured: true };
    const seen: string[] = [];
    new MutationObserver(() => seen.push(values(container)["Model"] ?? ""))
      .observe(container, { subtree: true, childList: true, characterData: true });
    native.restart(next, 1);
    await until(() => values(container)["Model"] === "fake-2", "the new Core's model");
    expect(seen).toContain(NOT_REPORTED);
    expect(seen.indexOf(NOT_REPORTED)).toBeLessThan(seen.indexOf("fake-2"));
    expect(seen.filter((model) => model === "fake-1").length).toBe(0);
  });

  test("a new workspace clears the Core's values at once", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    await openCore(container);
    await until(() => values(container)["Model"] === "fake-1", "the model");
    native.push(status({ workspace: "/work/other", workspace_id: "launch:2" }));
    await until(() => values(container)["Model"] === NOT_REPORTED || values(container)["Workspace"] === "/work/other",
                "cleared for the new workspace");
    expect(values(container)["Workspace"]).not.toBe("/work/project");
  });
});

describe("the actions", () => {
  test("are offered only when they apply, as the same commands", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    await openCore(container);
    const panel = container.querySelector<HTMLElement>('[role="dialog"][aria-label="Core"]')!;
    const labels = () => [...panel.querySelectorAll('[data-testid="core-panel"] button')]
      .map((button) => button.textContent);
    expect(labels()).toEqual(["Change workspace…"]);
    await click([...panel.querySelectorAll("button")].find((button) => button.textContent === "Change workspace…")!);
    expect(native.commands("choose_workspace").length).toBe(1);
    native.push(status({ state: "failed", core: null, failure: { class: "crashed", message: "x" } }));
    await until(() => labels().includes("Try again"), "Try again offered");
    expect(labels()).toEqual(["Change workspace…", "Try again"]);
  });
});
