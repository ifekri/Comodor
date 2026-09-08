import assert from "node:assert/strict";
import test from "node:test";

import type { QuestionField, QuestionRequest } from "@comodor/protocol";

import {
  allowsWriting,
  answer,
  answerable,
  begin,
  cancel,
  current,
  isSelected,
  move,
  optionAt,
  select,
  step,
  toggle,
  type,
} from "../src/index.ts";

function field(extra: Partial<QuestionField> = {}): QuestionField {
  return {
    header: "approach",
    prompt: "Which approach?",
    multiple: false,
    options: [
      { id: "Refactor the boundary", label: "Refactor the boundary" },
      { id: "Replace the frontend", label: "Replace the frontend" },
      { id: "Keep what is there", label: "Keep what is there" },
    ],
    ...extra,
  };
}

function form(...questions: QuestionField[]): QuestionRequest {
  return {
    id: "ask-1",
    session_id: "s1",
    title: questions.length === 1
      ? questions[0]!.prompt : `${questions.length} questions before I start`,
    questions: questions.length ? questions : [field()],
  };
}

test("a form starts on its first question and first option", () => {
  const state = begin(form());
  assert.equal(state.at, 0);
  assert.equal(state.cursor, 0);
  assert.equal(current(state)?.header, "approach");
  assert.equal(optionAt(state)?.id, "Refactor the boundary");
});

test("the option cursor wraps at both ends", () => {
  const state = begin(form());
  assert.equal(move(state, -1).cursor, 2);
  assert.equal(move(move(move(state, 1), 1), 1).cursor, 0);
});

test("stepping between questions does not wrap", () => {
  // The ends of a form mean something: past the last question is where a
  // person submits, not where they start again.
  const state = begin(form(field(), field({ header: "when" })));
  assert.equal(step(state, -1).at, 0);
  assert.equal(step(state, 1).at, 1);
  assert.equal(step(step(state, 1), 1).at, 1);
});

test("moving to another question resets the option cursor", () => {
  const state = step(move(begin(form(field(), field({ header: "when" }))), 2), 1);
  assert.equal(state.cursor, 0);
});

test("single choice replaces rather than accumulates", () => {
  let state = begin(form());
  state = toggle(state);
  state = select(state, "Keep what is there");
  assert.deepEqual(state.chosen[0], ["Keep what is there"]);
});

test("choosing the same single option twice leaves it chosen", () => {
  let state = toggle(begin(form()));
  state = toggle(state);
  assert.deepEqual(state.chosen[0], ["Refactor the boundary"]);
});

test("multiple choice accumulates and un-picks", () => {
  let state = begin(form(field({ multiple: true })));
  state = toggle(state);
  state = select(state, "Keep what is there");
  assert.deepEqual(state.chosen[0], ["Refactor the boundary", "Keep what is there"]);

  state = select(state, "Refactor the boundary");
  assert.deepEqual(state.chosen[0], ["Keep what is there"]);
  assert.ok(isSelected(state, "Keep what is there"));
});

test("each question keeps its own selection", () => {
  // The bug this prevents is one answer overwriting another, which is
  // invisible until somebody reads what the model was told.
  let state = begin(form(field(), field({ header: "when" })));
  state = toggle(state);
  state = step(state, 1);
  state = select(state, "Keep what is there");

  assert.deepEqual(state.chosen[0], ["Refactor the boundary"]);
  assert.deepEqual(state.chosen[1], ["Keep what is there"]);
});

test("an option that was never offered cannot be selected", () => {
  assert.deepEqual(select(begin(form()), "ghost").chosen[0], []);
});

test("writing is offered only where the form has a free row", () => {
  assert.equal(allowsWriting(begin(form())), false);

  const free = field({ options: [
    ...field().options,
    { id: "something else", label: "something else", free: true },
  ] });
  assert.equal(allowsWriting(begin(form(free))), true);
});

test("typed text is kept only where it is allowed", () => {
  assert.equal(type(begin(form()), "a fourth way").written[0], "");

  const free = field({ options: [
    { id: "write your own", label: "write your own", free: true },
  ] });
  const state = type(begin(form(free)), "a fourth way");
  assert.equal(state.written[0], "a fourth way");
  assert.ok(answerable(state));
});

test("nothing chosen and nothing typed is not answerable", () => {
  assert.equal(answerable(begin(form())), false);
});

test("the answer names every question by header", () => {
  // The core matches on header, never position: a reordered form would
  // otherwise silently reattach every answer to the wrong question.
  let state = begin(form(field(), field({ header: "when" })));
  state = toggle(state);

  assert.deepEqual(answer(state), {
    id: "ask-1",
    answers: [
      { header: "approach", chosen: ["Refactor the boundary"] },
      { header: "when", chosen: [] },
    ],
  });
});

test("an unanswered question is sent as empty rather than left out", () => {
  // Left out, it would be indistinguishable from a question the client did
  // not know about.
  const sent = answer(begin(form(field(), field({ header: "when" }))));
  assert.equal(sent.answers?.length, 2);
});

test("typed text rides alongside the chosen options", () => {
  const free = field({ options: [
    ...field().options,
    { id: "other", label: "other", free: true },
  ] });
  let state = begin(form(free));
  state = select(state, "Keep what is there");
  state = type(state, "  and document it  ");

  assert.deepEqual(answer(state).answers, [
    { header: "approach", chosen: ["Keep what is there"],
      written: "and document it" },
  ]);
});

test("cancelling names the form so the right one is resolved", () => {
  assert.deepEqual(cancel(begin(form())), { id: "ask-1", cancelled: true });
});

test("every transition returns a new object", () => {
  const state = begin(form());
  assert.notEqual(move(state, 1), state);
  assert.notEqual(toggle(state), state);
  assert.deepEqual(state.chosen[0], []);
});

test("the arrow keys do nothing while a person is typing", () => {
  const free = field({ options: [{ id: "own", label: "own", free: true }] });
  const state = type(begin(form(free)), "x");
  assert.equal(move(state, 1).cursor, state.cursor);
});
