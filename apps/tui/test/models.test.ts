/**
 * The model chooser's selection, without a terminal.
 *
 * The contract: the model in use opens highlighted, a query narrows and
 * re-seats the highlight, and Enter can never pick a row the list no longer
 * shows — the bug class this shares with the palette is an index carried
 * across a rebuilt list.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { move, open, search, selected, window } from "../src/models.ts";

const MODELS = ["fake-1", "fake-fast", "qwen3:8b", "deepseek-v4"];

test("the model in use opens highlighted", () => {
  const state = open(MODELS, "qwen3:8b");
  assert.equal(selected(state), "qwen3:8b");
});

test("an unknown current model highlights the first row", () => {
  const state = open(MODELS, "gone-model");
  assert.equal(selected(state), "fake-1");
});

test("a query narrows the list and re-seats the highlight", () => {
  // Starting mid-list is the trap: row 2 of the full list is not row 2 of
  // the filtered one, and an index kept across the change picks a model the
  // person never looked at.
  const opened = move(move(open(MODELS, "fake-1"), 1), 1);
  const narrowed = search(opened.all, opened.current, "fake");
  assert.deepEqual([...narrowed.matches], ["fake-1", "fake-fast"]);
  assert.equal(narrowed.index, 0);
  assert.equal(selected(narrowed), "fake-1");
});

test("a query that matches nothing selects nothing", () => {
  const state = search(MODELS, "fake-1", "zzzzz");
  assert.equal(state.matches.length, 0);
  assert.equal(selected(state), undefined);
});

test("the highlight wraps at both ends", () => {
  const state = open(MODELS, "fake-1");
  assert.equal(selected(move(state, -1)), "deepseek-v4");
  assert.equal(selected(move(move(move(move(state, 1), 1), 1), 1)), "fake-1");
});

test("the window keeps the highlight on screen", () => {
  let state = open(MODELS, "fake-1");
  for (let at = 0; at < 3; at++) state = move(state, 1);
  const { from, to } = window(state, 2);
  assert.ok(state.index >= from && state.index < to,
            `index ${state.index} outside [${from}, ${to})`);
});
