/**
 * The shell's layout rule (data-model §4): a pure function of the shell's
 * measured width — a fractional number of logical pixels, never rounded — and
 * the one stored layout. Nothing here is Core state.
 */

/** The surfaces the side panel shows; the conversation is the main area. */
export type PanelSurface = "core" | "diagnostics" | "shortcuts";

/** The stored layout (contracts/layout-persistence.md). */
export interface LayoutPreference {
  readonly version: 1;
  readonly panel_open: boolean;
  readonly panel_surface: PanelSurface;
  readonly panel_width: number;
}

export const DEFAULT_LAYOUT: LayoutPreference =
  { version: 1, panel_open: false, panel_surface: "core", panel_width: 320 };

/** Below this measured width the side panel covers the main area. */
export const COMPACT_BELOW = 900;
/** The main area's minimum width beside an open panel. */
export const MAIN_MIN = 360;
export const PANEL_MIN = 240;
/** The widest panel the native side stores. */
export const PANEL_MAX = 960;
/** One keyboard resize step. */
export const PANEL_STEP = 32;

export interface ShellLayout {
  readonly compact: boolean;
  readonly mode: "closed" | "beside" | "covering";
  /** The widest the panel may be shown at this width. */
  readonly room: number;
  /** The width the panel is shown at; the stored width is never rewritten. */
  readonly shownWidth: number;
}

export function shellLayout(width: number, rail: number, layout: LayoutPreference): ShellLayout {
  const compact = width < COMPACT_BELOW;
  const room = compact
    ? Math.max(0, width - rail)
    : Math.min(Math.max(0, width - rail - MAIN_MIN), width / 2);
  const shownWidth = compact
    ? Math.min(layout.panel_width, room)
    : Math.min(Math.max(layout.panel_width, PANEL_MIN), room);
  const mode = !layout.panel_open ? "closed" : compact ? "covering" : "beside";
  return { compact, mode, room, shownWidth };
}

/** Choose a surface: open the panel on it, or close it if it is the one shown. */
export function showSurface(layout: LayoutPreference, surface: PanelSurface): LayoutPreference {
  if (layout.panel_open && layout.panel_surface === surface) return { ...layout, panel_open: false };
  return { ...layout, panel_open: true, panel_surface: surface };
}

export function closePanel(layout: LayoutPreference): LayoutPreference {
  return { ...layout, panel_open: false };
}

/** A new width, kept from the minimum to the room and to what can be stored. */
export function resizePanel(layout: LayoutPreference, width: number, room: number): LayoutPreference {
  const upper = Math.min(Math.max(room, PANEL_MIN), PANEL_MAX);
  const panel_width = Math.round(Math.min(Math.max(width, PANEL_MIN), upper));
  return { ...layout, panel_width };
}

/** One keyboard step (`direction` +1 widens, -1 narrows) from the width shown. */
export function stepPanel(layout: LayoutPreference, direction: 1 | -1, room: number): LayoutPreference {
  const shown = Math.min(layout.panel_width, Math.max(room, PANEL_MIN));
  return resizePanel(layout, shown + direction * PANEL_STEP, room);
}
