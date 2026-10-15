/**
 * The layout preference in the window (US4; contracts/layout-persistence.md).
 *
 * Read once per page load with `read_layout`, started after the connection
 * so it never delays or reorders `connect`; anything that is not exactly
 * `{layout, stored}` with a valid layout means the defaults, without an
 * error. Written with `write_layout` after each completed change. A refused
 * or failed write keeps the window's layout as the person set it and says so
 * once, quietly; the next change writes again. Nothing here reaches the Core,
 * and the layout is the application's — not a workspace's or a session's.
 */

import type { NativeApi } from "../bridge.ts";
import { DEFAULT_LAYOUT, type LayoutPreference, PANEL_MAX, PANEL_MIN, type PanelSurface } from "./layout.ts";

const SURFACES: readonly PanelSurface[] = ["core", "diagnostics", "shortcuts"];
const FIELDS = ["version", "panel_open", "panel_surface", "panel_width"];

/** The layout in `value`, if it is exactly a valid one (the native rules, checked again here). */
export function asLayout(value: unknown): LayoutPreference | undefined {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return undefined;
  const fields = value as Record<string, unknown>;
  const keys = Object.keys(fields);
  if (keys.length !== FIELDS.length || !FIELDS.every((field) => keys.includes(field))) return undefined;
  const { version, panel_open, panel_surface, panel_width } = fields;
  if (version !== 1 || typeof panel_open !== "boolean") return undefined;
  if (typeof panel_surface !== "string" || !SURFACES.includes(panel_surface as PanelSurface)) return undefined;
  if (typeof panel_width !== "number" || !Number.isInteger(panel_width)
      || panel_width < PANEL_MIN || panel_width > PANEL_MAX) return undefined;
  return { version: 1, panel_open, panel_surface: panel_surface as PanelSurface, panel_width };
}

/** The layout a `read_layout` answer holds, or nothing. */
export function answeredLayout(answer: unknown): LayoutPreference | undefined {
  if (answer === null || typeof answer !== "object") return undefined;
  const fields = answer as Record<string, unknown>;
  if (Object.keys(fields).length !== 2 || typeof fields["stored"] !== "boolean") return undefined;
  return asLayout(fields["layout"]);
}

export interface LayoutState {
  readonly layout: LayoutPreference;
  /** A refused or failed write, said once; cleared by the next one that works. */
  readonly notice: string | null;
}

export class LayoutStore {
  private state: LayoutState = { layout: DEFAULT_LAYOUT, notice: null };
  private readonly listeners = new Set<() => void>();
  private reading: Promise<void> | undefined;
  /** A change made before the read answered wins over what the read brings. */
  private changed = false;

  constructor(private readonly api: NativeApi) {}

  get = (): LayoutState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** Read the stored layout, once per page load. */
  load(): Promise<void> {
    this.reading ??= this.api.invoke<unknown>("read_layout")
      .then((answer) => answeredLayout(answer))
      .catch(() => undefined)
      .then((layout) => {
        if (layout && !this.changed) this.update({ layout });
      });
    return this.reading;
  }

  /** A completed change: shown at once, then written. */
  set(layout: LayoutPreference): void {
    this.changed = true;
    if (!sameLayout(layout, this.state.layout)) this.update({ layout });
    void this.api.invoke("write_layout", { layout })
      .then(() => {
        if (this.state.notice !== null) this.update({ notice: null });
      })
      .catch((problem: unknown) => {
        const reason = problem instanceof Error ? problem.message : String(problem);
        this.update({ notice: `The layout could not be saved: ${reason}` });
      });
  }

  private update(next: Partial<LayoutState>): void {
    this.state = { ...this.state, ...next };
    for (const listener of this.listeners) listener();
  }
}

function sameLayout(left: LayoutPreference, right: LayoutPreference): boolean {
  return left.panel_open === right.panel_open && left.panel_surface === right.panel_surface
    && left.panel_width === right.panel_width;
}
