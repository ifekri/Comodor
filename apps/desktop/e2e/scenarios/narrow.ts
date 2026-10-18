/**
 * D2 T071, corrected 2026-10-17: narrow windows in the real WebView (US6;
 * FR-026, FR-027, FR-034, SC-007) — the sidebar beside the canvas from 900 px
 * and covering it below, the panel inside the window at every size, and the
 * essentials usable. Sizes are computed in physical pixels from the window's scale
 * factor `s`, so fractional scaling is always representable: the minimum
 * ceil(520·s) × ceil(400·s); ceil(900·s) − 1 and ceil(900·s) either side of
 * the threshold (899 and 900 at an integer scale); and a wide size fitted to
 * the monitor's work area. The threshold is judged by the width the shell
 * itself measures. Only a missing monitor or a display too small is
 * `capability-unavailable`.
 */

import { expect, type Scenario, type ScenarioContext, typeInto } from "../runner.ts";
import { panel, paletteControl, region, showSurface, SIDEBAR } from "./workbench.ts";

interface Size { readonly width: number; readonly height: number }
interface WindowReport {
  readonly inner: Size;
  readonly outer: Size;
  readonly scale_factor: number;
  readonly monitor: { readonly work_area: Size & { x: number; y: number }; readonly scale_factor: number } | null;
}

function frame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

async function windowNow(context: ScenarioContext): Promise<WindowReport> {
  return await context.query("window" as never) as unknown as WindowReport;
}

/** Wait, frame by frame, until `check` holds; false if it never does within the bound. */
async function observed(check: () => boolean | Promise<boolean>, frames = 900): Promise<boolean> {
  for (let count = 0; count < frames; count += 1) {
    if (await check()) return true;
    await frame();
  }
  return false;
}

function shellWidth(): number {
  return Number(document.querySelector('[data-testid="shell"]')?.getAttribute("data-width"));
}

function press(key: string, target: Element = document.activeElement ?? document.body): void {
  target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
}

function inView(element: Element | null, what: string): void {
  expect(element !== null, `${what} is there`);
  const rect = element!.getBoundingClientRect();
  expect(rect.width > 0 && rect.height > 0 && rect.left >= -1 && rect.top >= -1
         && rect.right <= window.innerWidth + 1 && rect.bottom <= window.innerHeight + 1,
         `${what} lies inside the viewport: ${JSON.stringify(rect)} in ${window.innerWidth}×${window.innerHeight}`);
}

/**
 * In view, and usable there: the element itself, or something inside it, is
 * what a pointer at its centre reaches — nothing covers it — and it is not
 * disabled unless `mayBeDisabled`.
 */
function usable(element: Element | null, what: string, mayBeDisabled = false): void {
  inView(element, what);
  const rect = element!.getBoundingClientRect();
  const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
  expect(hit !== null && (hit === element || element!.contains(hit)),
         `${what} is covered at its centre by ${hit?.outerHTML.slice(0, 80) ?? "nothing"}`);
  if (!mayBeDisabled) expect(!(element as HTMLButtonElement).disabled, `${what} is disabled`);
}

function noHorizontalScroll(where: string): void {
  const root = document.documentElement;
  expect(root.scrollWidth <= root.clientWidth, `${where}: the page scrolls horizontally (${root.scrollWidth} > ${root.clientWidth})`);
  for (const selector of ["header.top-bar", SIDEBAR, "main", "footer.status-bar", '[role="dialog"].modal-panel']) {
    const element = document.querySelector<HTMLElement>(selector);
    if (element) expect(element.scrollWidth <= element.clientWidth + 1, `${where}: ${selector} scrolls horizontally`);
  }
}

const toggle = () => document.querySelector<HTMLButtonElement>("button.sidebar-toggle");

export const narrow: Scenario = async (context) => {
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  await context.waitFor(() => document.querySelector('[data-testid="session"]'));

  const before = await windowNow(context);
  if (before.monitor === null) throw new Error("capability-unavailable: no monitor reported");
  const s = before.scale_factor;
  // What the window calls its inner size, less the page's: on macOS Tauri
  // counts the title bar inside the inner size, so the page is that much
  // shorter; on Windows and Linux the two are the same. The offset must be
  // zero there, a title bar's height on macOS, and the same at every size.
  const titleBar = Math.round(before.inner.height / s - window.innerHeight);
  const mac = navigator.userAgent.includes("Mac OS X");
  expect(Math.abs(before.inner.width / s - window.innerWidth) <= 1,
         `product-failure: the page is ${window.innerWidth} wide in an inner width of ${before.inner.width / s}`);
  expect(mac ? titleBar >= 0 && titleBar <= 40 : Math.abs(titleBar) <= 1,
         `product-failure: the page is ${titleBar} px shorter than the window's inner height on ${
           mac ? "macOS" : "this platform"}`);
  const pageHeight = (height: number) => height - (mac ? titleBar : 0);
  const frameWidth = before.outer.width - before.inner.width;
  const frameHeight = before.outer.height - before.inner.height;
  const area = before.monitor.work_area;
  const fits = (size: Size) => size.width + frameWidth <= area.width && size.height + frameHeight <= area.height;
  const height = Math.ceil(600 * s);
  const wide = {
    width: Math.min(Math.floor(1280 * s), area.width - frameWidth),
    height: Math.min(Math.floor(720 * s), area.height - frameHeight),
  };
  const sizes: { name: string; size: Size }[] = [
    { name: "minimum", size: { width: Math.ceil(520 * s), height: Math.ceil(400 * s) } },
    // Wide enough for the eight menus, as short as the minimum: the menus must scroll.
    { name: "short", size: { width: Math.ceil(800 * s), height: Math.ceil(400 * s) } },
    { name: "below", size: { width: Math.ceil(900 * s) - 1, height } },
    { name: "at", size: { width: Math.ceil(900 * s), height } },
    { name: "wide", size: wide },
  ];
  if (wide.width < Math.ceil(1000 * s) || wide.height < height || !sizes.every(({ size }) => fits(size))) {
    throw new Error(`capability-unavailable: the runner's display is too small (work area ${area.width}×${
      area.height}, frame ${frameWidth}×${frameHeight}, scale ${s})`);
  }

  const results: Record<string, unknown>[] = [];
  // A control the footer sheds when it narrows holds the focus before the
  // first (smallest) size: the focus must not fall to the page.
  const shed = document.querySelector<HTMLElement>('[data-testid="composer"] .prompt-shortcuts');
  shed?.focus();
  let first = shed !== null && document.activeElement === shed;
  for (const { name, size } of sizes) {
    await context.checkpoint("resize", { width: size.width, height: size.height });
    const applied = await observed(async () => {
      const now = await windowNow(context);
      return now.inner.width === size.width && now.inner.height === size.height;
    });
    if (!applied) throw new Error(`product-failure: ${name} ${size.width}×${size.height} never applied`);
    const logical = { width: size.width / s, height: size.height / s };
    // Fresh: the shell's measurement has caught up with its box (a ResizeObserver
    // reports after layout), and both are within 1 px of physical ÷ s.
    const box = () => document.querySelector('[data-testid="shell"]')!.getBoundingClientRect().width;
    const settled = await observed(() => Math.abs(shellWidth() - box()) < 0.01
      && Math.abs(shellWidth() - logical.width) <= 1
      && Math.abs(window.innerWidth - logical.width) <= 1 && Math.abs(window.innerHeight - pageHeight(logical.height)) <= 1);
    if (!settled) {
      // What the window and the page each said, so a mismatch can be told apart.
      const now = await windowNow(context);
      expect(false, `product-failure: ${name}: page ${window.innerWidth}×${window.innerHeight} and shell ${
        shellWidth()} are not within 1 px of ${logical.width}×${pageHeight(logical.height)} (title bar ${
        mac ? titleBar : 0}); window ${JSON.stringify(now)
      }; document ${document.documentElement.clientWidth}×${document.documentElement.clientHeight}, visual viewport ${
        window.visualViewport?.width}×${window.visualViewport?.height}, screen ${screen.width}×${screen.height}`);
    }
    const measured = shellWidth();
    const compact = measured < 900;
    if (first) {
      first = false;
      await observed(() => document.activeElement !== shed, 120);
      const active = document.activeElement;
      expect(active !== null && active !== document.body && active.getClientRects().length > 0,
             `product-failure: ${name}: the focus fell to the page when the footer shed its focused control (${
               active?.outerHTML.slice(0, 60) ?? "nothing"})`);
    }

    // The sidebar's mode, judged by the measured width alone (FR-026).
    const mode = document.querySelector('[data-testid="shell"]')?.getAttribute("data-mode");
    expect(mode === (compact ? "covering" : "beside"), `product-failure: ${name}: ${mode} at ${measured}`);
    usable(toggle(), `${name}: the sidebar toggle`);
    if (compact) {
      expect(document.querySelector(SIDEBAR) === null, `${name}: the sidebar is hidden below 900`);
      toggle()!.focus();
      toggle()!.click();
      const covering = await context.waitFor(() => document.querySelector<HTMLElement>("nav.sidebar-covering"));
      inView(covering, `${name}: the covering sidebar`);
      const box = covering.getBoundingClientRect();
      const top = document.querySelector("header.top-bar")!.getBoundingClientRect().bottom;
      const bottom = document.querySelector("footer.status-bar")!.getBoundingClientRect().top;
      expect(Math.abs(box.top - top) <= 1 && Math.abs(box.bottom - bottom) <= 1,
             `product-failure: ${name}: the covering sidebar spans ${box.top}–${box.bottom}, not ${top}–${bottom}`);
      expect(await observed(() => region() === "sidebar", 120), `${name}: focus moved into the covering sidebar`);
      press("Escape");
      await context.waitFor(() => document.querySelector(SIDEBAR) === null);
      expect(document.activeElement === toggle(), `${name}: Escape gave focus back to the sidebar toggle`);
    } else {
      inView(document.querySelector("nav.sidebar-beside"), `${name}: the sidebar beside the canvas`);
    }

    // The panel: drawn inside the window at every size; focus in, F6 around, Escape out.
    await showSurface(context, "Core");
    const opener = document.querySelector('header.top-bar button[data-menu="Option"]')
      ?? document.querySelector('header.top-bar button[data-menu="Menu"]');
    expect(await observed(() => region() === "panel", 120), `${name}: focus moved into the panel`);
    inView(panel(), `${name}: the panel`);
    const around = compact ? "status,top,main,panel" : "status,top,sidebar,main,panel";
    const seen: (string | null)[] = [];
    for (let count = 0; count < around.split(",").length; count += 1) {
      press("F6");
      seen.push(region());
    }
    expect(seen.join(",") === around, `${name}: F6 cycle ${seen.join(",")}`);
    press("Escape");
    await context.waitFor(() => panel() === null);
    expect(document.activeElement === opener, `${name}: Escape gave focus back to the menu that opened the panel`);

    // At every size, with the panel closed: the essentials in view, nothing scrolling sideways.
    noHorizontalScroll(name);
    inView(document.querySelector('[data-testid="composer"] textarea'), `${name}: the composer`);
    inView([...document.querySelectorAll<HTMLButtonElement>('[data-testid="composer"] button')]
      .find((button) => button.textContent === "Send") ?? null, `${name}: Send`);
    inView(document.querySelector(".status-state"), `${name}: the Core state`);
    inView(paletteControl(), `${name}: the palette control`);

    // ...and usable where they are (FR-027): nothing covers them, and they work.
    const textarea = document.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    const send = () => [...document.querySelectorAll<HTMLButtonElement>('[data-testid="composer"] button')]
      .find((button) => button.textContent === "Send") ?? null;
    usable(textarea, `${name}: the composer`);
    usable(send(), `${name}: Send`, true);
    usable(document.querySelector(".status-state"), `${name}: the Core state`);
    usable(paletteControl(), `${name}: the palette control`);
    // The menus, or "Menu" when they fold below 760 px.
    const menus = [...document.querySelectorAll<HTMLButtonElement>("header.top-bar button[data-menu]")];
    expect(menus.length === (measured < 760 ? 1 : 8), `${name}: ${menus.length} menu triggers at ${measured}`);
    for (const button of menus) usable(button, `${name}: the menu ${button.textContent}`);
    // Each menu, open, ends above the status bar; its last item, scrolled to, is reachable.
    const barTop = document.querySelector("footer.status-bar")!.getBoundingClientRect().top;
    for (const button of menus) {
      button.click();
      const menu = await context.waitFor(() => document.querySelector<HTMLElement>('[role="menu"]'));
      const box = menu.getBoundingClientRect();
      expect(box.bottom <= barTop + 1,
             `product-failure: ${name}: the ${button.textContent} menu runs to ${box.bottom}, past the status bar at ${barTop}`);
      const last = [...menu.querySelectorAll<HTMLElement>('[role="menuitem"]')].at(-1)!;
      last.scrollIntoView({ block: "nearest" });
      usable(last, `${name}: the last item of the ${button.textContent} menu`, true);
      button.click();
      await context.waitFor(() => document.querySelector('[role="menu"]') === null);
    }
    for (const button of document.querySelectorAll<HTMLButtonElement>('nav[aria-label="Mode"] button')) {
      usable(button, `${name}: the mode ${button.textContent}`);
    }
    // Ready, so "Change workspace…" is offered: its absence fails, like any essential's.
    usable(document.querySelector<HTMLButtonElement>("footer.status-bar .status-change"), `${name}: Change workspace…`);
    // A draft makes Send available; it is not sent, and the draft is cleared.
    textarea.focus();
    typeInto(textarea, "a draft at this size");
    await context.waitFor(() => send()?.disabled === false);
    usable(send(), `${name}: Send with a draft`);
    typeInto(textarea, "");
    // The palette control opens the palette inside the window; Escape closes it.
    paletteControl()!.focus();
    paletteControl()!.click();
    const dialog = await context.element('[role="dialog"][aria-label="Commands"]');
    inView(dialog, `${name}: the palette`);
    usable(dialog.querySelector('[role="combobox"]'), `${name}: the palette's field`);
    press("Escape", dialog.querySelector('[role="combobox"]')!);
    await context.waitFor(() => document.querySelector('[role="dialog"][aria-label="Commands"]') === null);
    expect(document.activeElement === paletteControl(), `${name}: Escape gave focus back to the palette control`);
    noHorizontalScroll(`${name}, after use`);
    const shellElement = document.querySelector('[data-testid="shell"]')!;
    results.push({ name, requested: size, logical, measured, page: { width: window.innerWidth, height: window.innerHeight },
                   document: document.documentElement.clientWidth, body: document.body.getBoundingClientRect().width,
                   shellBox: shellElement.getBoundingClientRect().width, mode, scale: s });
  }
  return { outcome: "verified", workArea: area, frame: { width: frameWidth, height: frameHeight }, scale: s,
           titleBarInInner: mac ? titleBar : 0,
           monitorScale: before.monitor.scale_factor, sizes: results };
};
