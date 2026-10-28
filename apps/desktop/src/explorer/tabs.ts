/**
 * Which files are open as tabs, and which tab is shown (D3a).
 *
 * The thread — the conversation — is always the first tab and is not in this
 * list. Only paths are kept, in the window's per-launch storage, so tabs
 * survive a page reload and a Core restart within a launch; a file's text is
 * never stored, and a relaunch starts with the thread alone.
 */

const KEY = "comodor.tabs";

export interface TabsState {
  readonly open: readonly string[];
  /** The path of the shown file, or null for the thread. */
  readonly active: string | null;
}

const EMPTY: TabsState = { open: [], active: null };

function load(storage: Storage | undefined): TabsState {
  try {
    const raw = storage?.getItem(KEY);
    if (!raw) return EMPTY;
    const data = JSON.parse(raw) as { open?: unknown; active?: unknown };
    const open = Array.isArray(data.open) ? data.open.filter((path): path is string => typeof path === "string") : [];
    const active = typeof data.active === "string" && open.includes(data.active) ? data.active : null;
    return { open: [...new Set(open)], active };
  } catch {
    return EMPTY;
  }
}

export class TabsStore {
  private state: TabsState;
  private readonly listeners = new Set<() => void>();

  constructor(private readonly storage: Storage | undefined) {
    this.state = load(storage);
  }

  readonly get = (): TabsState => this.state;

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** Open `path` (one tab per file) and show it. */
  open(path: string): void {
    const open = this.state.open.includes(path) ? this.state.open : [...this.state.open, path];
    this.set({ open, active: path });
  }

  /** Show `path`, or the thread when null. */
  show(path: string | null): void {
    if (path !== null && !this.state.open.includes(path)) return;
    this.set({ ...this.state, active: path });
  }

  /** Close `path`; closing the shown tab shows its neighbour, or the thread. */
  close(path: string): void {
    const at = this.state.open.indexOf(path);
    if (at < 0) return;
    const open = this.state.open.filter((other) => other !== path);
    let active = this.state.active;
    if (active === path) active = open[at] ?? open[at - 1] ?? null;
    this.set({ open, active });
  }

  /** A new workspace: no file of the old one stays open. */
  clear(): void {
    this.set(EMPTY);
  }

  private set(next: TabsState): void {
    this.state = next;
    try {
      this.storage?.setItem(KEY, JSON.stringify(next));
    } catch {
      // Storage refused: tabs still work for this page.
    }
    for (const listener of this.listeners) listener();
  }
}

/** A path's last segment: the name a tab shows. */
export function baseName(path: string): string {
  return path.split("/").pop() || path;
}
