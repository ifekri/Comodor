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

  restore(root: ParentNode = document): void {
    const opener = this.openers.pop();
    const usable = opener instanceof HTMLElement && opener.isConnected
      && !(opener as HTMLButtonElement).disabled ? opener : null;
    (usable ?? fallbackTarget(root))?.focus();
  }
}

/** The shell's regions in order: rail, main area, side panel (when shown), status bar. */
export function regions(root: ParentNode): HTMLElement[] {
  return [
    root.querySelector<HTMLElement>('nav[aria-label="Workbench"]'),
    root.querySelector<HTMLElement>("main"),
    root.querySelector<HTMLElement>("aside"),
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
