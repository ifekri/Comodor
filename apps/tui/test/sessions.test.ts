/**
 * The session picker's selection, without a terminal.
 *
 * The contract is the chooser's: a query narrows and re-seats the highlight,
 * and Enter can never open a session the rebuilt list no longer shows.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { move, open, search, selected, when, window } from "../src/sessions.ts";

const NOW = 1_800_000_000;
const ENTRIES = [
  { id: "a1", title: "fix the parser", messages: 12, updatedAt: NOW - 60 },
  { id: "b2", title: "add the tests", messages: 40, updatedAt: NOW - 7200 },
  { id: "c3", title: "survey the cache", messages: 6, updatedAt: NOW - 90000 },
];

test("the newest conversation opens highlighted", () => {
  const state = open(ENTRIES);
  assert.equal(selected(state)?.id, "a1");
});

test("a query narrows by title and re-seats the highlight", () => {
  const state = search(ENTRIES, "cache");
  assert.deepEqual(state.matches.map((entry) => entry.id), ["c3"]);
  assert.equal(selected(state)?.id, "c3");
});

test("a query matches the id as well as the title", () => {
  const state = search(ENTRIES, "b2");
  assert.equal(state.matches.length, 1);
  assert.equal(selected(state)?.id, "b2");
});

test("a query that matches nothing opens nothing", () => {
  const state = search(ENTRIES, "zzzzz");
  assert.equal(state.matches.length, 0);
  assert.equal(selected(state), undefined);
});

test("the highlight wraps, and the window keeps it on screen", () => {
  let state = open(ENTRIES);
  state = move(state, -1);
  assert.equal(selected(state)?.id, "c3");
  const { from, to } = window(state, 2);
  assert.ok(state.index >= from && state.index < to);
});

test("the age reads as a person reads it", () => {
  const now = Date.now() / 1000;
  assert.equal(when(now - 10), "just now");
  assert.equal(when(now - 900), "15m ago");
  assert.equal(when(now - 7200), "2h ago");
  assert.equal(when(now - 200_000), "2d ago");
  assert.equal(when(now - 8_000_000), "3mo ago");
});
