import assert from "node:assert/strict";
import test from "node:test";

import type { QuestionRequest } from "@comodor/protocol";

import {
  answer,
  answerable,
  begin,
  cancel,
  isSelected,
  move,
  optionAt,
  select,
  toggle,
  type,
} from "../src/index.ts";

function question(extra: Partial<QuestionRequest> = {}): QuestionRequest {
  return {
    id: "q1",
    session_id: "s1",
    title: "Which approach?",
    options: [
      { id: "refactor", label: "Refactor the boundary" },
      { id: "replace", label: "Replace the frontend" },
      { id: "keep", label: "Keep what is there" },
    ],
    multiple: false,
    ...extra,
  };
}

test("a single-choice question starts on the first option", () => {
  const state = begin(question());
  assert.equal(state.cursor, 0);
  assert.deepEqual(state.selected, []);
  assert.equal(optionAt(state)?.id, "refactor");
});

test("a default selection is honoured and puts the cursor on it", () => {
  const state = begin(question({ default: ["keep"] }));
  assert.deepEqual(state.selected, ["keep"]);
  assert.equal(state.cursor, 2);
});

test("a default naming an option that is not offered is dropped", () => {
  // Otherwise it is submitted as a selection nobody could see or unselect.
  const state = begin(question({ default: ["ghost"] }));
  assert.deepEqual(state.selected, []);
});

test("the cursor wraps at both ends", () => {
  const state = begin(question());
  assert.equal(move(state, -1).cursor, 2);
  assert.equal(move(move(state, 1), 1).cursor, 2);
  assert.equal(move(move(move(state, 1), 1), 1).cursor, 0);
});

test("single choice replaces rather than accumulates", () => {
  let state = begin(question());
  state = toggle(state);
  state = select(state, "keep");

  assert.deepEqual(state.selected, ["keep"]);
});

test("choosing the same single option twice leaves it chosen", () => {
  // A radio button with nothing selected is a state a person cannot get back
  // from without knowing they caused it.
  let state = begin(question());
  state = toggle(state);
  state = toggle(state);

  assert.deepEqual(state.selected, ["refactor"]);
});

test("multiple choice accumulates and un-picks", () => {
  let state = begin(question({ multiple: true }));
  state = toggle(state);
  state = select(state, "keep");
  assert.deepEqual(state.selected, ["refactor", "keep"]);

  state = select(state, "refactor");
  assert.deepEqual(state.selected, ["keep"]);
  assert.ok(isSelected(state, "keep"));
});

test("an option that was never offered cannot be selected", () => {
  const state = select(begin(question()), "ghost");
  assert.deepEqual(state.selected, []);
});

test("custom text is refused unless the question allows it", () => {
  const state = type(begin(question()), "something else");
  assert.equal(state.custom, "");
  assert.equal(state.writing, false);
});

test("custom text is kept when the question allows it", () => {
  const state = type(begin(question({ allow_custom: true })), "a fourth way");
  assert.equal(state.custom, "a fourth way");
  assert.ok(answerable(state));
});

test("nothing chosen and nothing typed is not answerable", () => {
  assert.equal(answerable(begin(question())), false);
});

test("the answer carries the ids the core will match on", () => {
  let state = begin(question({ multiple: true }));
  state = select(state, "replace");
  state = select(state, "keep");

  assert.deepEqual(answer(state), { id: "q1", selected: ["replace", "keep"] });
});

test("custom text rides alongside the selection", () => {
  let state = begin(question({ allow_custom: true }));
  state = select(state, "keep");
  state = type(state, "  and document it  ");

  assert.deepEqual(answer(state),
    { id: "q1", selected: ["keep"], custom: "and document it" });
});

test("cancelling names the question so the right one is resolved", () => {
  assert.deepEqual(cancel(begin(question())), { id: "q1", cancelled: true });
});

test("every transition returns a new object", () => {
  // State something else is already drawing must not change underneath it.
  const state = begin(question());
  assert.notEqual(move(state, 1), state);
  assert.notEqual(toggle(state), state);
  assert.deepEqual(state.selected, []);
});

test("the arrow keys do nothing while a person is typing", () => {
  const state = type(begin(question({ allow_custom: true })), "x");
  assert.equal(move(state, 1).cursor, state.cursor);
});
