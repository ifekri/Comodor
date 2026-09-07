/**
 * A question, as state rather than as prose.
 *
 * The old shape was a model writing "1. Refactor  2. Replace  3. Keep" into
 * its answer and a person typing a number back. That works until the list is
 * long, or the terminal wraps it, or the model numbers from zero — and it
 * cannot be rendered as a control by anything, because there is nothing to
 * render but text.
 *
 * `question.requested` carries the real thing, and this holds the selection
 * while a person moves through it. Deliberately no rendering: a terminal draws
 * radio buttons out of it, a browser draws a form, and both agree about what
 * is selected because there is one reducer.
 *
 * Every transition returns a new object. A reducer that mutates is one that
 * eventually mutates state something else is already drawing.
 */

import type { QuestionOption, QuestionRequest } from "@comodor/protocol";

export interface QuestionState {
  readonly question: QuestionRequest;
  /** Where the keyboard is. Always a valid index while there are options. */
  readonly cursor: number;
  /** Option ids, in the order they were chosen. */
  readonly selected: readonly string[];
  /** What a person typed, when the question allows it. */
  readonly custom: string;
  /** Whether the custom field has the keyboard. */
  readonly writing: boolean;
}

export function begin(question: QuestionRequest): QuestionState {
  const defaults = question.default ?? [];
  const known = new Set(question.options.map((option) => option.id));
  // A default naming an option that is not offered is dropped rather than
  // carried: it would be submitted as a selection nobody could see.
  const selected = defaults.filter((id) => known.has(id));
  const first = selected[0];
  const at = first === undefined
    ? 0
    : Math.max(0, question.options.findIndex((option) => option.id === first));
  return {
    question,
    cursor: at,
    selected: question.multiple ? selected : selected.slice(0, 1),
    custom: "",
    writing: false,
  };
}

export function move(state: QuestionState, by: number): QuestionState {
  const count = state.question.options.length;
  if (count === 0 || state.writing) return state;
  // Wraps, because a list short enough to fit on a screen is one where
  // pressing down at the bottom obviously means "the first one".
  const cursor = (state.cursor + by + count) % count;
  return { ...state, cursor };
}

export function toggle(state: QuestionState): QuestionState {
  const option = state.question.options[state.cursor];
  if (!option) return state;
  return select(state, option.id);
}

export function select(state: QuestionState, id: string): QuestionState {
  const known = state.question.options.some((option) => option.id === id);
  if (!known) return state;

  if (!state.question.multiple) {
    // Single choice: picking one replaces whatever was picked before, and
    // picking the same one again leaves it picked rather than clearing it —
    // a radio button with no selection is a state a person cannot get back
    // from without knowing they caused it.
    return { ...state, selected: [id] };
  }
  const selected = state.selected.includes(id)
    ? state.selected.filter((entry) => entry !== id)
    : [...state.selected, id];
  return { ...state, selected };
}

export function type(state: QuestionState, text: string): QuestionState {
  if (!state.question.allow_custom) return state;
  return { ...state, custom: text, writing: true };
}

export function startWriting(state: QuestionState): QuestionState {
  return state.question.allow_custom ? { ...state, writing: true } : state;
}

export function stopWriting(state: QuestionState): QuestionState {
  return { ...state, writing: false };
}

/** Whether Enter would send anything. */
export function answerable(state: QuestionState): boolean {
  return state.selected.length > 0 || state.custom.trim().length > 0;
}

/** The parameters for `question.answer`. */
export function answer(state: QuestionState): {
  id: string; selected: string[]; custom?: string;
} {
  const body: { id: string; selected: string[]; custom?: string } = {
    id: state.question.id,
    selected: [...state.selected],
  };
  const custom = state.custom.trim();
  if (custom) body.custom = custom;
  return body;
}

export function cancel(state: QuestionState): {
  id: string; cancelled: true;
} {
  return { id: state.question.id, cancelled: true };
}

export function optionAt(state: QuestionState): QuestionOption | undefined {
  return state.question.options[state.cursor];
}

export function isSelected(state: QuestionState, id: string): boolean {
  return state.selected.includes(id);
}
