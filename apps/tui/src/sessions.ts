/**
 * The session picker's selection, as state.
 *
 * Same pattern as the model chooser for the same reason: "does Up move the
 * highlight, does Enter open what is highlighted, and does a query change
 * keep pointing at what it pointed at" is answerable without a terminal.
 *
 * The rows are the core's `session.history` answer, fetched when the picker
 * opens — never a cached copy, because a store shared with other surfaces
 * changes while this client is looking elsewhere.
 */

/** One stored conversation, as `session.history` describes it. */
export interface SessionEntry {
  readonly id: string;
  readonly title: string;
  readonly messages: number;
  readonly updatedAt: number;
}

export interface SessionPickerState {
  readonly query: string;
  /** The core's whole list, unfiltered — re-filtering starts from it. */
  readonly all: readonly SessionEntry[];
  /** The entries matching the query, in the core's order. */
  readonly matches: readonly SessionEntry[];
  /** Which match is highlighted. Always valid, or -1 when there are none. */
  readonly index: number;
}

export function open(entries: readonly SessionEntry[]): SessionPickerState {
  return search(entries, "");
}

export function search(entries: readonly SessionEntry[],
                       query: string): SessionPickerState {
  const needle = query.trim().toLowerCase();
  const matches = needle
    ? entries.filter((entry) =>
        entry.title.toLowerCase().includes(needle)
        || entry.id.toLowerCase().includes(needle))
    : [...entries];
  // A query change re-seats the highlight on the first match: an index kept
  // across a rebuilt list points at whatever happens to sit there now, which
  // is a session nobody was looking at.
  return { query, all: [...entries], matches,
           index: matches.length ? 0 : -1 };
}

export function move(state: SessionPickerState,
                     by: number): SessionPickerState {
  const count = state.matches.length;
  if (count === 0) return state;
  const index = ((state.index < 0 ? 0 : state.index) + by + count) % count;
  return { ...state, index };
}

export function selected(state: SessionPickerState): SessionEntry | undefined {
  return state.index < 0 ? undefined : state.matches[state.index];
}

/** How many rows a client draws, and where the window starts. */
export function window(state: SessionPickerState, rows: number):
    { from: number; to: number } {
  if (rows <= 0 || state.matches.length === 0) return { from: 0, to: 0 };
  const count = state.matches.length;
  if (count <= rows) return { from: 0, to: count };
  const half = Math.floor(rows / 2);
  const from = Math.max(0, Math.min(count - rows, Math.max(0, state.index) - half));
  return { from, to: from + rows };
}

/** `3h ago`, `2d ago`, `just now` — as a picker row reads it. */
export function when(updatedAt: number): string {
  const delta = Math.max(0, Date.now() / 1000 - updatedAt);
  if (delta < 90) return "just now";
  if (delta < 3600) return `${Math.round(delta / 60)}m ago`;
  if (delta < 86_400) return `${Math.round(delta / 3600)}h ago`;
  if (delta < 30 * 86_400) return `${Math.round(delta / 86_400)}d ago`;
  return `${Math.round(delta / (30 * 86_400))}mo ago`;
}
