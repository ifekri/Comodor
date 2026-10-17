/**
 * Focus in the shell (FR-018, FR-019; data-model §8): where focus returns
 * when an overlay or panel closes, and the cycle between regions. Nothing
 * here traps focus.
 */

const TABBABLE = [
  "button:not([disabled])", "a[href]", "input:not([disabled])", "textarea:not([disabled])",
  "select:not([disabled])", '[tabindex]:not([tabindex="-1"])',
].join(", ");

/** The composer's field, else the main area: where focus lands when its origin is gone. */
export function fallbackTarget(root: ParentNode = document): HTMLElement | null {
  return root.querySelector<HTMLElement>('[data-testid="composer"] textarea')
    ?? root.querySelector<HTMLElement>("main");
}

/**
 * The elements that opened each panel or overlay, most recent last. Closing
 * returns focus to that element if it is still in the document, otherwise to
 * the composer, otherwise to the main area.
 */
export class FocusReturn {
  private readonly openers: (Element | null)[] = [];

  push(opener: Element | null): void {
    this.openers.push(opener);
  }

  /** Forget the most recent opener without moving focus. */
  drop(): void {
    this.openers.pop();
  }

  /** Take the most recent opener off, to give focus back to it later. */
  take(): Element | null {
    return this.openers.pop() ?? null;
  }

  restore(root: ParentNode = document): void {
    focusBack(this.openers.pop() ?? null, root);
  }
}

/** An element that can take focus now: in the document and not disabled. */
export function isUsable(element: Element | null | undefined): element is HTMLElement {
  return element instanceof HTMLElement && element.isConnected && !(element as HTMLButtonElement).disabled;
}

/**
 * Give focus back to an opener: the element itself, else the one drawn anew
 * in its place (the top bar's search, replaced by the palette while it is
 * open) found by its focus key, else the composer, else the main area.
 */
export function focusBack(opener: Element | null, root: ParentNode = document): void {
  const key = opener instanceof HTMLElement ? opener.dataset["focusKey"] : undefined;
  const again = key === undefined ? null : root.querySelector<HTMLElement>(`[data-focus-key="${key}"]`);
  (isUsable(opener) ? opener : isUsable(again) ? again : fallbackTarget(root))?.focus();
}

/**
 * The shell's regions in order (spec Clarifications, 2026-10-17): the top
 * bar, the sidebar (when shown), the canvas, the panel (when open), the
 * status bar.
 */
export function regions(root: ParentNode): HTMLElement[] {
  return [
    root.querySelector<HTMLElement>("header.top-bar"),
    root.querySelector<HTMLElement>('nav[aria-label="Workbench"]'),
    root.querySelector<HTMLElement>("main"),
    root.querySelector<HTMLElement>('[role="dialog"].modal-panel'),
    root.querySelector<HTMLElement>("footer.status-bar"),
  ].filter((region): region is HTMLElement => region !== null);
}

/** Focus the first focusable element of a region, or the region itself. */
export function focusRegion(region: HTMLElement): void {
  const first = region.querySelector<HTMLElement>(TABBABLE);
  if (first) {
    first.focus();
    return;
  }
  if (!region.hasAttribute("tabindex")) region.setAttribute("tabindex", "-1");
  region.focus();
}

/** Move focus to the next (`by` 1) or previous (`by` -1) region, around again. */
export function cycleRegions(root: ParentNode, by: 1 | -1): void {
  const all = regions(root);
  if (all.length === 0) return;
  const active = document.activeElement;
  const at = all.findIndex((region) => region === active || region.contains(active));
  const next = at < 0 ? (by === 1 ? 0 : all.length - 1) : (at + by + all.length) % all.length;
  focusRegion(all[next]!);
}

/** Move focus into a panel: its first focusable element, or the panel. */
export function focusInto(panel: HTMLElement | null): void {
  if (panel) focusRegion(panel);
}
