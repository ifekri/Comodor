/**
 * D2 T071: narrow windows in the real WebView (US6; FR-025–FR-027, FR-034,
 * SC-007). Sizes are computed in physical pixels from the window's scale
 * factor `s`, so fractional scaling is always representable: the minimum
 * ceil(520·s) × ceil(400·s); ceil(900·s) − 1 and ceil(900·s) either side of
 * the threshold (899 and 900 at an integer scale); and a wide size fitted to
 * the monitor's work area. The threshold is judged by the width the shell
 * itself measures. Only a missing monitor or a display too small is
 * `capability-unavailable`.
 */

import { expect, type Scenario, type ScenarioContext, typeInto } from "../runner.ts";

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

function region(): string | null {
  const active = document.activeElement;
  if (!active) return null;
  if (active.closest('nav[aria-label="Workbench"]')) return "rail";
  if (active.closest("main")) return "main";
  if (active.closest("aside")) return "panel";
  if (active.closest("footer.status-bar")) return "status";
  return null;
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
  for (const selector of ['nav[aria-label="Workbench"]', "main", "footer.status-bar", "aside"]) {
    const element = document.querySelector<HTMLElement>(selector);
    if (element) expect(element.scrollWidth <= element.clientWidth + 1, `${where}: ${selector} scrolls horizontally`);
  }
}

const coreButton = () => document.querySelector<HTMLButtonElement>('nav[aria-label="Workbench"] button[aria-label="Core"]')!;
const panel = () => document.querySelector<HTMLElement>("aside");

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
    { name: "below", size: { width: Math.ceil(900 * s) - 1, height } },
    { name: "at", size: { width: Math.ceil(900 * s), height } },
    { name: "wide", size: wide },
  ];
  if (wide.width < Math.ceil(1000 * s) || wide.height < height || !sizes.every(({ size }) => fits(size))) {
    throw new Error(`capability-unavailable: the runner's display is too small (work area ${area.width}×${
      area.height}, frame ${frameWidth}×${frameHeight}, scale ${s})`);
  }

  const results: Record<string, unknown>[] = [];
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

    // The panel's mode, judged by the measured width alone.
    const opener = coreButton();
    opener.focus();
    opener.click();
    await context.waitFor(() => panel());
    const mode = panel()!.classList.contains("side-panel-covering") ? "covering" : "beside";
    expect(mode === (compact ? "covering" : "beside"), `product-failure: ${name}: ${mode} at ${measured}`);
    expect(document.querySelector('[data-testid="shell"]')?.getAttribute("data-mode") === mode,
           `product-failure: ${name}: data-mode`);
    expect(region() === "panel", `${name}: focus moved into the panel`);

    // F6 around the regions at this size.
    const seen: (string | null)[] = [];
    for (let count = 0; count < 4; count += 1) {
      press("F6");
      seen.push(region());
    }
    expect(seen.join(",") === "status,rail,main,panel", `${name}: F6 cycle ${seen.join(",")}`);

    if (mode === "beside") {
      const edge = panel()!.querySelector<HTMLElement>('[role="separator"]')!;
      edge.focus();
      const was = Number(edge.getAttribute("aria-valuenow"));
      press("ArrowLeft", edge);
      await observed(() => Number(edge.getAttribute("aria-valuenow")) !== was, 120);
      const now = Number(edge.getAttribute("aria-valuenow"));
      expect(now >= 240 && now <= Number(edge.getAttribute("aria-valuemax")), `${name}: keyboard resize in range`);
      coreButton().click();
    } else {
      press("Escape", panel()!);
      await context.waitFor(() => panel() === null);
      expect(document.activeElement === opener, `${name}: Escape gave focus back to the rail`);
    }
    await context.waitFor(() => panel() === null);

    // At every size, with the panel closed: the essentials in view, nothing scrolling sideways.
    noHorizontalScroll(name);
    inView(document.querySelector('[data-testid="composer"] textarea'), `${name}: the composer`);
    inView([...document.querySelectorAll<HTMLButtonElement>('[data-testid="composer"] button')]
      .find((button) => button.textContent === "Send") ?? null, `${name}: Send`);
    inView(document.querySelector(".status-state"), `${name}: the Core state`);
    inView(document.querySelector('footer.status-bar button[aria-label="Commands"]'), `${name}: the palette control`);

    // ...and usable where they are (FR-027): nothing covers them, and they work.
    const textarea = document.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    const send = () => [...document.querySelectorAll<HTMLButtonElement>('[data-testid="composer"] button')]
      .find((button) => button.textContent === "Send") ?? null;
    usable(textarea, `${name}: the composer`);
    usable(send(), `${name}: Send`, true);
    usable(document.querySelector(".status-state"), `${name}: the Core state`);
    const paletteControl = document.querySelector<HTMLButtonElement>('footer.status-bar button[aria-label="Commands"]');
    usable(paletteControl, `${name}: the palette control`);
    for (const button of document.querySelectorAll<HTMLButtonElement>('nav[aria-label="Workbench"] button')) {
      usable(button, `${name}: the rail's ${button.getAttribute("aria-label")}`);
    }
    for (const button of document.querySelectorAll<HTMLButtonElement>('nav[aria-label="Mode"] button')) {
      usable(button, `${name}: the mode ${button.textContent}`);
    }
    const change = document.querySelector<HTMLButtonElement>("footer.status-bar .status-change");
    if (change) usable(change, `${name}: Change workspace…`);
    // A draft makes Send available; it is not sent, and the draft is cleared.
    textarea.focus();
    typeInto(textarea, "a draft at this size");
    await context.waitFor(() => send()?.disabled === false);
    usable(send(), `${name}: Send with a draft`);
    typeInto(textarea, "");
    // The palette control opens the palette inside the window; Escape closes it.
    paletteControl!.focus();
    paletteControl!.click();
    const dialog = await context.element('[role="dialog"][aria-label="Commands"]');
    inView(dialog, `${name}: the palette`);
    usable(dialog.querySelector('[role="combobox"]'), `${name}: the palette's field`);
    press("Escape", dialog.querySelector('[role="combobox"]')!);
    await context.waitFor(() => document.querySelector('[role="dialog"][aria-label="Commands"]') === null);
    expect(document.activeElement === paletteControl, `${name}: Escape gave focus back to the palette control`);
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
