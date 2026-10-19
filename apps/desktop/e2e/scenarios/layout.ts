/**
 * D2 T058: the layout preference through the real bridge (US4; FR-021,
 * FR-023, FR-036, SC-008, SC-009, SC-017).
 *
 * A refused write is checked between two in-run reads of the preferences
 * file, immediately before and after it — before the application closes,
 * because D1 saves the window's geometry on close, which legitimately
 * changes the file.
 */

import { invoke } from "@tauri-apps/api/core";

import { expect, type Scenario, type ScenarioContext, withText } from "../runner.ts";
import { panel, showSurface } from "./workbench.ts";

const PLACE = "comodor-e2e-layout-place";

async function ready(context: ScenarioContext): Promise<void> {
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  await context.waitFor(() => document.querySelector('[data-testid="session"]'));
}

async function preferences(context: ScenarioContext): Promise<{ bytes: string | null; temporary: boolean }> {
  const reply = await context.checkpoint("read-preferences");
  return { bytes: (reply["bytes"] as string | null) ?? null, temporary: reply["temporary"] === true };
}

/** Wait, frame by frame, for a Core other than `pid`; a bound, not a delay. */
async function anotherCore(context: ScenarioContext, pid: number): Promise<boolean> {
  for (let frame = 0; frame < 1200; frame += 1) {
    const now = Number((await context.query("core_pid"))["pid"]);
    if (now > 0 && now !== pid) return true;
    await new Promise((resolve) => requestAnimationFrame(() => resolve(undefined)));
  }
  return false;
}

/** The arranged layout: the panel open on a surface other than the default (FR-025: the width is not drawn). */
function arranged(): boolean {
  return panel()?.getAttribute("aria-label") === "Diagnostics";
}

export const layout: Scenario = async (context) => {
  const place = sessionStorage.getItem(PLACE);
  await ready(context);

  if (place === null) {
    // Arrange: the Diagnostics panel open.
    await showSurface(context, "Diagnostics");
    await context.waitFor(() => arranged());
    sessionStorage.setItem(PLACE, "reloaded");
    location.reload();
    return new Promise(() => {});
  }

  // Reload: restored.
  await context.waitFor(() => arranged());
  sessionStorage.removeItem(PLACE);

  // A crash and the restart: kept.
  const { pid } = await context.query("core_pid");
  await context.checkpoint("kill-core", { pid });
  expect(await anotherCore(context, Number(pid)), "a new Core started after the crash");
  await ready(context);
  expect(arranged(), "the layout is kept across a Core restart");

  // A workspace change: kept.
  withText("footer.status-bar button", "Change workspace…")!.click();
  const stored = String(context.params["stored"]);
  await context.waitFor(() =>
    document.querySelector('[data-testid="status-strip"][data-state="ready"] .status-workspace')?.textContent === stored);
  await context.waitFor(() => document.querySelector('[data-testid="session"]'));
  expect(arranged(), "the layout is kept across a workspace change");

  // A refused write through the real bridge: the file's bytes do not move.
  const before = await preferences(context);
  expect(before.bytes !== null, "the layout was stored");
  let refused = "";
  try {
    await invoke("write_layout", { layout: { version: 1, panel_open: true, panel_surface: "core", panel_width: 4000 } });
  } catch (problem) {
    refused = String(problem);
  }
  const after = await preferences(context);
  expect(refused.includes("panel_width"), `refused with its reason: ${refused}`);
  expect(after.bytes === before.bytes, "the preferences file is byte-identical after the refused write");
  expect(!after.temporary, "no temporary file is left");
  const file = JSON.parse(atob(after.bytes!)) as Record<string, unknown>;
  return { refused, layout: file["layout"], hasWindow: "window" in file };
};

/** A file seeded with a layout that is not valid: the defaults, D1's values intact. */
export const layoutSeeded: Scenario = async (context) => {
  await ready(context);
  const expectOpen = context.params["expect"] === "restored";
  if (expectOpen) {
    await context.waitFor(() => panel()?.getAttribute("aria-label") === "Keyboard shortcuts");
    expect(panel()!.style.width === "", `the stored width is carried, not drawn: ${panel()!.style.width}`);
  } else {
    expect(panel() === null, "the defaults: no panel");
  }
  const file = await preferences(context);
  const stored = JSON.parse(atob(file.bytes!)) as Record<string, unknown>;
  // Field by field: the params reach the page through serde_json, which orders keys.
  const window_ = stored["window"] as Record<string, unknown> | undefined;
  const expected = context.params["window"] as Record<string, unknown>;
  expect(window_ !== undefined && Object.keys(expected).every((field) => window_[field] === expected[field])
         && Object.keys(window_).length === Object.keys(expected).length,
         `D1's window geometry is intact: ${JSON.stringify(window_)} vs ${JSON.stringify(expected)}`);
  expect(stored["last_selected_folder"] === context.params["folder"],
         `D1's last folder is intact: ${String(stored["last_selected_folder"])}`);
  return { panel: panel()?.getAttribute("aria-label") ?? null };
};
