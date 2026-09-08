/**
 * The command palette's selection, as state.
 *
 * Separated from the component for the same reason the question reducer is:
 * "does Up move the selection, and does Enter run what is highlighted" is
 * answerable without a terminal, and it is the part that goes wrong.
 *
 * The rule that needs stating is what happens when the query changes. The
 * result list is rebuilt on every keystroke, so an index kept across that
 * change points at a different command — or at nothing. Typing therefore puts
 * the selection back on the first result, which is also the one a person
 * means when they type three letters and press Enter.
 */

import type { Command, CommandRegistry } from "@comodor/commands";

export interface PaletteState<Context> {
  readonly query: string;
  /** Which result is highlighted. Always valid, or -1 when there are none. */
  readonly index: number;
  readonly results: readonly Command<Context>[];
}

export function open<Context>(
  registry: CommandRegistry<Context>, context: Context,
): PaletteState<Context> {
  return search(registry, context, "");
}

export function search<Context>(
  registry: CommandRegistry<Context>, context: Context, query: string,
): PaletteState<Context> {
  const results = registry.search(query, context);
  // Back to the top on every change: an index carried across a rebuilt list
  // highlights whatever happens to be at that position now, which is not what
  // anybody selected.
  return { query, index: results.length ? 0 : -1, results };
}

export function move<Context>(
  state: PaletteState<Context>, by: number,
): PaletteState<Context> {
  const count = state.results.length;
  if (count === 0) return state;
  // Wraps, because a list that fits on a screen is one where pressing down at
  // the bottom obviously means the first.
  const index = ((state.index < 0 ? 0 : state.index) + by + count) % count;
  return { ...state, index };
}

export function selected<Context>(
  state: PaletteState<Context>,
): Command<Context> | undefined {
  return state.index < 0 ? undefined : state.results[state.index];
}

/** How many rows a client draws, and where the window starts. */
export function window<Context>(
  state: PaletteState<Context>, rows: number,
): { from: number; to: number } {
  if (rows <= 0 || state.results.length === 0) return { from: 0, to: 0 };
  const count = state.results.length;
  if (count <= rows) return { from: 0, to: count };
  // Keep the selection on screen: scroll only when it would fall off, so a
  // list does not jump under somebody moving one row at a time.
  const half = Math.floor(rows / 2);
  const from = Math.max(0, Math.min(count - rows, Math.max(0, state.index) - half));
  return { from, to: from + rows };
}
