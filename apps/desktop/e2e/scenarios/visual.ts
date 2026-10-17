/**
 * D2 SC-018 (correction 2026-10-17): the real window at the reference's
 * sizes and in its states, captured by the operating system for comparison
 * with the `_ide_ui` reference — 1440 × 900 (the reference's viewport), 900
 * and 899 (either side of the sidebar's threshold) as viewports, and the
 * minimum native window 520 × 400 (FR-027) — each in the normal, menu,
 * palette and panel states, below 900 also with the covering sidebar, and
 * then with a question asked.
 *
 * A size the window never reaches (a runner's display too small) is recorded
 * `capability-unavailable` with what was measured, never captured at another
 * size in its place; the result's outcome is then `partial`. A state that
 * does not show, or a capture that fails at a size the window reached, fails
 * the scenario.
 */

import { expect, pressKey, type Scenario, type ScenarioContext, typeInto, withText } from "../runner.ts";
import { panel, paletteControl, showSurface, SIDEBAR } from "./workbench.ts";

interface Size { readonly width: number; readonly height: number }
interface WindowReport {
  readonly inner: Size;
  readonly outer: Size;
  readonly scale_factor: number;
  readonly monitor: { readonly work_area: Size & { x: number; y: number } } | null;
}

const QUESTION_PROMPT = "Build the service. Which database: SQLite or PostgreSQL?";

/** The viewports of the reference, and the minimum native window. */
const SIZES: readonly { name: string; width: number; height: number; native?: boolean }[] = [
  { name: "1440x900", width: 1440, height: 900 },
  { name: "900x600", width: 900, height: 600 },
  { name: "899x600", width: 899, height: 600 },
  { name: "520x400-minimum", width: 520, height: 400, native: true },
];

function frame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

async function observed(check: () => boolean | Promise<boolean>, frames = 600): Promise<boolean> {
  for (let count = 0; count < frames; count += 1) {
    if (await check()) return true;
    await frame();
  }
  return false;
}

async function windowNow(context: ScenarioContext): Promise<WindowReport> {
  return await context.query("window" as never) as unknown as WindowReport;
}

/** Drawn and still: fonts loaded, no animation running, two frames painted. */
async function settled(): Promise<void> {
  await document.fonts.ready;
  await observed(() => document.getAnimations().every((animation) => animation.playState !== "running"), 240);
  await frame();
  await frame();
}

type Shot = Record<string, unknown>;

async function shoot(context: ScenarioContext, name: string, shots: Shot[]): Promise<void> {
  await settled();
  const reply = await context.checkpoint("screenshot", { name });
  const shot = reply["shot"] as Shot | undefined;
  expect(shot?.["ok"] === true, `product-failure: the window could not be captured for ${name}: ${
    String(shot?.["reason"] ?? "no reply")}`);
  shots.push({ name, page: { width: window.innerWidth, height: window.innerHeight }, ...shot });
}

/** Resize the window; the page size reached, or null when the window never gets there. */
async function resize(context: ScenarioContext, size: (typeof SIZES)[number], titleBar: number):
    Promise<{ requested: Size; page: Size } | null> {
  const s = (await windowNow(context)).scale_factor;
  // A viewport is the page's size; the minimum is the native window's (FR-027).
  const height = size.native ? size.height : size.height + titleBar;
  const requested = { width: Math.ceil(size.width * s), height: Math.ceil(height * s) };
  await context.checkpoint("resize", requested);
  const reached = await observed(async () => {
    const now = await windowNow(context);
    return now.inner.width === requested.width && now.inner.height === requested.height
      && Math.abs(window.innerWidth - requested.width / s) <= 1;
  });
  if (!reached) return null;
  await observed(() => Math.abs(Number(document.querySelector('[data-testid="shell"]')?.getAttribute("data-width"))
    - window.innerWidth) < 1, 120);
  return { requested, page: { width: window.innerWidth, height: window.innerHeight } };
}

export const visual: Scenario = async (context) => {
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  await context.waitFor(() => document.querySelector('[data-testid="session"]'));
  const before = await windowNow(context);
  const s = before.scale_factor;
  // On macOS the page is shorter than the inner size by the title bar (FR-027).
  const mac = navigator.userAgent.includes("Mac OS X");
  const titleBar = mac ? Math.max(0, Math.round(before.inner.height / s - window.innerHeight)) : 0;
  const shots: Shot[] = [];
  const sizes: Record<string, unknown>[] = [];
  const reachedSizes: (typeof SIZES)[number][] = [];

  for (const size of SIZES) {
    const reached = await resize(context, size, titleBar);
    if (reached === null) {
      const now = await windowNow(context);
      sizes.push({ name: size.name, outcome: "capability-unavailable",
                   reason: `the window never reached ${size.width}×${size.height}${size.native ? " (native)" : ""}`,
                   window: now.inner, workArea: now.monitor?.work_area ?? null });
      continue;
    }
    reachedSizes.push(size);
    sizes.push({ name: size.name, outcome: "captured", ...reached,
                 mode: document.querySelector('[data-testid="shell"]')?.getAttribute("data-mode") });

    await shoot(context, `${size.name}-normal`, shots);

    // A menu open: the reference's File menu, or "Menu" when the menus fold.
    const trigger = document.querySelector<HTMLButtonElement>('header.top-bar button[data-menu="File"]')
      ?? document.querySelector<HTMLButtonElement>('header.top-bar button[data-menu="Menu"]')!;
    trigger.click();
    await context.waitFor(() => document.querySelector('[role="menu"]'));
    await shoot(context, `${size.name}-menu`, shots);
    trigger.click();
    await context.waitFor(() => document.querySelector('[role="menu"]') === null);

    paletteControl()!.click();
    const input = await context.element('[role="dialog"][aria-label="Commands"] [role="combobox"]');
    await shoot(context, `${size.name}-palette`, shots);
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    await context.waitFor(() => document.querySelector('[role="dialog"][aria-label="Commands"]') === null);

    await showSurface(context, "Core");
    await shoot(context, `${size.name}-panel`, shots);
    panel()!.querySelector<HTMLButtonElement>(".modal-done")!.click();
    await context.waitFor(() => panel() === null);

    if (document.querySelector('[data-testid="shell"]')?.getAttribute("data-mode") === "covering") {
      document.querySelector<HTMLButtonElement>("button.sidebar-toggle")!.click();
      await context.waitFor(() => document.querySelector("nav.sidebar-covering"));
      await shoot(context, `${size.name}-sidebar`, shots);
      document.querySelector<HTMLElement>('[data-testid="sidebar-backdrop"]')!.click();
      await context.waitFor(() => document.querySelector(SIDEBAR) === null);
    }
  }

  // A question asked: the conversation and the question card, at each size reached.
  await context.waitFor(() => {
    const send = withText('[data-testid="composer"] button', "Send") as HTMLButtonElement | null;
    return send !== null && !send.disabled;
  });
  const field = await context.element('[data-testid="composer"] textarea');
  typeInto(field, QUESTION_PROMPT);
  pressKey(field, "Enter");
  await context.element('[data-testid="form"]');
  for (const size of reachedSizes) {
    const reached = await resize(context, size, titleBar);
    expect(reached !== null, `product-failure: ${size.name} was reached before and not now`);
    await context.element('[data-testid="form"]');
    await shoot(context, `${size.name}-question`, shots);
    // With a question asked, the composer and Send stay in view (FR-027).
    for (const [what, element] of [["the composer", field],
                                   ["Send", withText('[data-testid="composer"] button', "Send")]] as const) {
      const rect = element?.getBoundingClientRect();
      expect(rect !== undefined && rect.height > 0 && rect.top >= 0 && rect.bottom <= window.innerHeight + 1
             && rect.right <= window.innerWidth + 1,
             `product-failure: ${size.name}: ${what} is out of view with a question asked (${JSON.stringify(rect)})`);
    }
  }

  const unavailable = sizes.filter((entry) => entry["outcome"] !== "captured").map((entry) => entry["name"]);
  return { outcome: unavailable.length === 0 ? "verified" : "partial", unavailable, titleBarInInner: titleBar,
           scale: s, workArea: before.monitor?.work_area ?? null, sizes, shots, platform: navigator.userAgent };
};
