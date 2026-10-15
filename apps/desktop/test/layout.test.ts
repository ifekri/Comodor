/**
 * The shell's layout rule (data-model §4; FR-025, FR-026). A pure function of
 * the shell's measured width — fractional logical pixels, never rounded — and
 * the stored layout.
 */

import { describe, expect, test } from "bun:test";

import {
  closePanel, COMPACT_BELOW, DEFAULT_LAYOUT, MAIN_MIN, PANEL_MIN, PANEL_STEP, type LayoutPreference,
  resizePanel, shellLayout, showSurface, stepPanel,
} from "../src/shell/layout.ts";

const RAIL = 56;

function layout(overrides: Partial<LayoutPreference> = {}): LayoutPreference {
  return { ...DEFAULT_LAYOUT, panel_open: true, ...overrides };
}

describe("the compact threshold", () => {
  test("is 900 logical pixels, on the fractional measured width", () => {
    expect(COMPACT_BELOW).toBe(900);
    expect(shellLayout(899.2, RAIL, layout()).compact).toBe(true);
    expect(shellLayout(899.99, RAIL, layout()).compact).toBe(true);
    expect(shellLayout(900.0, RAIL, layout()).compact).toBe(false);
    expect(shellLayout(520, RAIL, layout()).compact).toBe(true);
    expect(shellLayout(1600, RAIL, layout()).compact).toBe(false);
  });

  test("covers below it and sits beside at or above it", () => {
    expect(shellLayout(899.99, RAIL, layout()).mode).toBe("covering");
    expect(shellLayout(900.0, RAIL, layout()).mode).toBe("beside");
    expect(shellLayout(1600, RAIL, layout({ panel_open: false })).mode).toBe("closed");
    expect(shellLayout(520, RAIL, layout({ panel_open: false })).mode).toBe("closed");
  });
});

describe("the room and the shown width", () => {
  const widths = [520, 899.2, 899.99, 900.0, 1600];
  const stored = [240, 320, 960];

  test("beside: never below the panel minimum, never squeezing the main area under its minimum, never past half the window", () => {
    for (const w of widths.filter((width) => width >= COMPACT_BELOW)) {
      for (const panel_width of stored) {
        const shell = shellLayout(w, RAIL, layout({ panel_width }));
        expect(shell.room).toBeLessThanOrEqual(w / 2);
        expect(shell.room).toBeLessThanOrEqual(w - RAIL - MAIN_MIN);
        expect(shell.shownWidth).toBeGreaterThanOrEqual(PANEL_MIN);
        expect(shell.shownWidth).toBeLessThanOrEqual(shell.room);
        expect(w - RAIL - shell.shownWidth).toBeGreaterThanOrEqual(MAIN_MIN);
      }
    }
  });

  test("covering: the panel covers the main area, up to the room beside the rail", () => {
    for (const w of widths.filter((width) => width < COMPACT_BELOW)) {
      for (const panel_width of stored) {
        const shell = shellLayout(w, RAIL, layout({ panel_width }));
        expect(shell.room).toBe(w - RAIL);
        expect(shell.shownWidth).toBe(Math.min(panel_width, w - RAIL));
      }
    }
  });

  test("exact values at the boundaries", () => {
    expect(shellLayout(900, RAIL, layout({ panel_width: 320 }))).toMatchObject(
      { compact: false, mode: "beside", room: 450, shownWidth: 320 });
    expect(shellLayout(900, RAIL, layout({ panel_width: 960 })).shownWidth).toBe(450);
    expect(shellLayout(1600, RAIL, layout({ panel_width: 960 })).shownWidth).toBe(800);
    expect(shellLayout(1600, RAIL, layout({ panel_width: 240 })).shownWidth).toBe(240);
    expect(shellLayout(520, RAIL, layout({ panel_width: 960 })).shownWidth).toBe(464);
  });

  test("a stored width wider than the room is shown limited and never rewritten", () => {
    const stored = layout({ panel_width: 960 });
    const before = { ...stored };
    const shell = shellLayout(900, RAIL, stored);
    expect(shell.shownWidth).toBeLessThan(960);
    expect(stored).toEqual(before);
    expect(shellLayout(2400, RAIL, stored).shownWidth).toBe(960);
  });
});

describe("the transitions", () => {
  test("choosing a surface opens the panel on it; choosing the shown one closes it", () => {
    const closed = { ...DEFAULT_LAYOUT };
    const opened = showSurface(closed, "diagnostics");
    expect(opened).toEqual({ ...closed, panel_open: true, panel_surface: "diagnostics" });
    expect(showSurface(opened, "core")).toEqual({ ...opened, panel_surface: "core" });
    expect(showSurface(opened, "diagnostics")).toEqual({ ...opened, panel_open: false });
  });

  test("closing keeps the surface and the width", () => {
    const opened = layout({ panel_surface: "shortcuts", panel_width: 400 });
    expect(closePanel(opened)).toEqual({ ...opened, panel_open: false });
  });

  test("resizing stays from 240 to the room, and within what can be stored", () => {
    expect(resizePanel(layout(), 100, 450).panel_width).toBe(240);
    expect(resizePanel(layout(), 700, 450).panel_width).toBe(450);
    expect(resizePanel(layout(), 400.6, 800).panel_width).toBe(401);
    expect(resizePanel(layout(), 5000, 5000).panel_width).toBe(960);
  });

  test("a keyboard step moves 32 pixels within the range", () => {
    expect(PANEL_STEP).toBe(32);
    expect(stepPanel(layout({ panel_width: 320 }), +1, 450).panel_width).toBe(352);
    expect(stepPanel(layout({ panel_width: 320 }), -1, 450).panel_width).toBe(288);
    expect(stepPanel(layout({ panel_width: 250 }), -1, 450).panel_width).toBe(240);
    expect(stepPanel(layout({ panel_width: 440 }), +1, 450).panel_width).toBe(450);
    // A step starts from the width shown, not from a stored width the room cuts.
    expect(stepPanel(layout({ panel_width: 960 }), -1, 450).panel_width).toBe(418);
  });

  test("the defaults are the contract's", () => {
    expect(DEFAULT_LAYOUT).toEqual({ version: 1, panel_open: false, panel_surface: "core", panel_width: 320 });
  });
});
