/**
 * T036: in each of SC-004's eight states the palette lists exactly the
 * commands whose "Enabled when" rule (contracts/workbench-shell.md) holds —
 * zero that would do nothing, zero missing (FR-012, FR-015, SC-004).
 *
 * In every case the palette is open (so "Commands" itself is not listed),
 * the panel is closed, and the composer is empty.
 */

import { afterEach, describe, expect, test } from "bun:test";

import type { CoreStatus } from "../src/bridge.ts";
import { App } from "../src/app.tsx";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { render, type Rendered, until } from "./render.ts";
import { openPalette, optionIds } from "./shell-helpers.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

/** Applies in every state: the shell's own layout and navigation. */
const ALWAYS = ["view.conversation", "view.core", "view.diagnostics", "view.shortcuts", "layout.reset",
                "region.next", "region.previous", "sidebar.toggle"];

/** A session shown, the Core ready, ACT confirmed, nothing busy. */
const SESSION = ["composer.focus", "view.tail", "mode.plan", "mode.ask", "mode.next", "mode.previous"];

const EXPECTED: Record<string, string[]> = {
  ready: [...ALWAYS, ...SESSION, "workspace.change"],
  unconfigured: [...ALWAYS, ...SESSION, "workspace.change", "core.check_again"],
  starting: [...ALWAYS, "workspace.change"],
  checking: [...ALWAYS, "composer.focus", "view.tail", "workspace.change"],
  restarting: [...ALWAYS, "workspace.change"],
  failed: [...ALWAYS, "workspace.change", "core.retry"],
  closing: [...ALWAYS, "app.quit_now"],
  "no workspace": [...ALWAYS, "workspace.change"],
};

async function listed(native: FakeNative, after?: (native: FakeNative) => void,
                      session = true): Promise<string[]> {
  const view = session ? (await openWindow(show, until, native)).container
    : (await show(native)).container;
  if (!session) await until(() => view.querySelector('[data-testid="status-strip"]'), "the strip");
  after?.(native);
  return [...optionIds(await openPalette(view).then(() => view))].sort();
}

describe("the palette lists exactly what applies", () => {
  test("ready", async () => {
    expect(await listed(new FakeNative())).toEqual([...EXPECTED["ready"]!].sort());
  });

  test("unconfigured", async () => {
    const native = new FakeNative();
    native.core.model = { provider: "fake", model: "fake-1", configured: false };
    const view = (await show(native)).container;
    await until(() => view.querySelector('[data-testid="setup-notice"]'), "the setup notice");
    await openPalette(view);
    expect([...optionIds(view)].sort()).toEqual([...EXPECTED["unconfigured"]!].sort());
  });

  test("checking (the wake check holds the session)", async () => {
    const native = new FakeNative();
    const view = (await openWindow(show, until, native)).container;
    native.push(status({ state: "checking", check_epoch: 1 }));
    await until(() => view.querySelector('[data-testid="status-strip"][data-state="checking"]'), "checking");
    await openPalette(view);
    expect([...optionIds(view)].sort()).toEqual([...EXPECTED["checking"]!].sort());
  });

  const WITHOUT_SESSION: Record<string, Partial<CoreStatus>> = {
    starting: { state: "starting", core: null },
    restarting: { state: "restarting", restart_count: 1, core: null },
    failed: { state: "failed", core: null, failure: { class: "crashed", message: "it stopped" } },
    closing: { state: "stopping", closing: { seconds_remaining: 7 } },
    "no workspace": { state: "absent", workspace: null, workspace_id: null, core: null, notice: null },
  };
  for (const [name, overrides] of Object.entries(WITHOUT_SESSION)) {
    test(name, async () => {
      expect(await listed(new FakeNative(status(overrides)), undefined, false))
        .toEqual([...EXPECTED[name]!].sort());
    });
  }
});
