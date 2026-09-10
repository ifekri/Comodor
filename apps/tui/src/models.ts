/**
 * The model chooser's selection, as state.
 *
 * Same shape as the palette for the same reason: "does Up move the highlight,
 * does Enter pick what is highlighted, and what happens when the query
 * changes" is answerable without a terminal, and it is the part that goes
 * wrong.
 *
 * The list itself is not filtered to death: the query narrows it, and a model
 * id that matches nothing typed so far is still reachable by clearing the
 * query. The core's list is the whole truth — there is no client-side
 * catalogue to keep in step.
 */

export interface ModelPickerState {
  readonly query: string;
  /** The core's whole list, unfiltered — re-filtering starts from it. */
  readonly all: readonly string[];
  /** The models matching the query, in the core's order. */
  readonly matches: readonly string[];
  /** Which match is highlighted. Always valid, or -1 when there are none. */
  readonly index: number;
  /** The model in use right now, marked in the list rather than hidden. */
  readonly current: string;
}

export function open(models: readonly string[], current: string,
                     ): ModelPickerState {
  return search(models, current, "");
}

export function search(models: readonly string[], current: string,
                       query: string): ModelPickerState {
  const needle = query.trim().toLowerCase();
  const matches = needle
    ? models.filter((model) => model.toLowerCase().includes(needle))
    : [...models];
  // The current model opens highlighted: the chooser answers "where am I"
  // before it answers "where could I go", and Enter on the unchanged row is
  // the no-op it reads as. A query change re-seats the highlight on the first
  // match, because an index kept across a rebuilt list points at whatever
  // happens to sit there now.
  const index = matches.length === 0 ? -1
    : needle ? 0
    : Math.max(0, matches.indexOf(current));
  return { query, all: [...models], matches, index, current };
}

export function move(state: ModelPickerState, by: number): ModelPickerState {
  const count = state.matches.length;
  if (count === 0) return state;
  const index = ((state.index < 0 ? 0 : state.index) + by + count) % count;
  return { ...state, index };
}

export function selected(state: ModelPickerState): string | undefined {
  return state.index < 0 ? undefined : state.matches[state.index];
}

/** How many rows a client draws, and where the window starts. */
export function window(state: ModelPickerState, rows: number):
    { from: number; to: number } {
  if (rows <= 0 || state.matches.length === 0) return { from: 0, to: 0 };
  const count = state.matches.length;
  if (count <= rows) return { from: 0, to: count };
  const half = Math.floor(rows / 2);
  const from = Math.max(0, Math.min(count - rows, Math.max(0, state.index) - half));
  return { from, to: from + rows };
}
