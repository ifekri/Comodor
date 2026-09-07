/**
 * A form, as state rather than as prose.
 *
 * The old shape was a model writing "1. Refactor  2. Replace  3. Keep" into
 * its answer and a person typing a number back. That works until the list is
 * long, or the terminal wraps it, or the model numbers from zero — and it
 * cannot be rendered as a control by anything, because there is nothing to
 * render but text.
 *
 * **A form is several questions, not one.** The `ask` tool exists to put four
 * short questions before a person in one round trip rather than four, so a
 * client that flattened them to a single prompt would undo the tool. This
 * holds the position within the form and the selection within each question.
 *
 * Deliberately no rendering: a terminal draws radio buttons from it, a browser
 * draws a form, and both agree about what is selected because there is one
 * reducer. Every transition returns a new object — a reducer that mutates is
 * one that eventually mutates state something else is already drawing.
 */

import type {
  AnswerParams,
  QuestionAnswer,
  QuestionField,
  QuestionOption,
  QuestionRequest,
} from "@comodor/protocol";

export interface FormState {
  readonly form: QuestionRequest;
  /** Which question the person is on. */
  readonly at: number;
  /** Which option within it. */
  readonly cursor: number;
  /** Chosen option ids, per question, in the order they were picked. */
  readonly chosen: readonly (readonly string[])[];
  /** What was typed into the free row, per question. */
  readonly written: readonly string[];
  /** Whether the free row has the keyboard. */
  readonly writing: boolean;
}

export function begin(form: QuestionRequest): FormState {
  return {
    form,
    at: 0,
    cursor: 0,
    chosen: form.questions.map(() => []),
    written: form.questions.map(() => ""),
    writing: false,
  };
}

export function current(state: FormState): QuestionField | undefined {
  return state.form.questions[state.at];
}

export function optionAt(state: FormState): QuestionOption | undefined {
  return current(state)?.options[state.cursor];
}

/** Move within the current question's options. Wraps. */
export function move(state: FormState, by: number): FormState {
  const question = current(state);
  if (!question || question.options.length === 0 || state.writing) return state;
  const count = question.options.length;
  return { ...state, cursor: (state.cursor + by + count) % count };
}

/** Move between questions. Does not wrap — the ends of a form are meaningful. */
export function step(state: FormState, by: number): FormState {
  const at = state.at + by;
  if (at < 0 || at >= state.form.questions.length) return state;
  return { ...state, at, cursor: 0, writing: false };
}

export function toggle(state: FormState): FormState {
  const option = optionAt(state);
  return option ? select(state, option.id) : state;
}

export function select(state: FormState, id: string): FormState {
  const question = current(state);
  if (!question) return state;
  if (!question.options.some((option) => option.id === id)) return state;

  const chosen = state.chosen[state.at] ?? [];
  let next: string[];
  if (!question.multiple) {
    // Single choice replaces, and picking the same one again leaves it
    // picked: a radio button with nothing selected is a state a person
    // cannot get back from without knowing they caused it.
    next = [id];
  } else {
    next = chosen.includes(id)
      ? chosen.filter((entry) => entry !== id)
      : [...chosen, id];
  }
  return { ...state, chosen: replaceAt(state.chosen, state.at, next) };
}

/** Whether the current question offers a write-your-own row. */
export function allowsWriting(state: FormState): boolean {
  return Boolean(current(state)?.options.some((option) => option.free));
}

export function type(state: FormState, text: string): FormState {
  if (!allowsWriting(state)) return state;
  return {
    ...state,
    written: replaceAt(state.written, state.at, text),
    writing: true,
  };
}

export function startWriting(state: FormState): FormState {
  return allowsWriting(state) ? { ...state, writing: true } : state;
}

export function stopWriting(state: FormState): FormState {
  return { ...state, writing: false };
}

export function isSelected(state: FormState, id: string): boolean {
  return (state.chosen[state.at] ?? []).includes(id);
}

/** Whether anything at all has been answered. */
export function answerable(state: FormState): boolean {
  return state.form.questions.some((_question, index) =>
    (state.chosen[index] ?? []).length > 0
    || (state.written[index] ?? "").trim().length > 0);
}

/**
 * The parameters for `question.answer`.
 *
 * Every question is included, answered or not. A question left out would be
 * indistinguishable from one the client did not know about, and the core
 * matches on `header` rather than position for the same reason.
 */
export function answer(state: FormState): AnswerParams {
  const answers: QuestionAnswer[] = state.form.questions.map(
    (question, index) => {
      const written = (state.written[index] ?? "").trim();
      const entry: QuestionAnswer = {
        header: question.header,
        chosen: [...(state.chosen[index] ?? [])],
      };
      return written ? { ...entry, written } : entry;
    });
  return { id: state.form.id, answers };
}

export function cancel(state: FormState): AnswerParams {
  return { id: state.form.id, cancelled: true };
}

function replaceAt<T>(items: readonly T[], at: number, value: T): T[] {
  const copy = [...items];
  copy[at] = value;
  return copy;
}
