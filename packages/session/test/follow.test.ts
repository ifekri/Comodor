/**
 * Auto-follow policy: what follows from where the viewport is and what has
 * arrived. The scrolling itself belongs to the renderer, and is proved
 * against the real one in `apps/tui/test/bun`.
 */

import { strictEqual as is } from "node:assert/strict";
import { test } from "node:test";

import {
  followMarker,
  followMoved,
  followSent,
  followStart,
  followTail,
  grew,
} from "../src/index.ts";

test("it follows the newest content by default", () => {
  is(followStart.following, true);
  is(followStart.unseen, false);
  is(followMarker(followStart), false);
});

test("growing while following changes nothing", () => {
  const state = grew(followStart);
  is(state.following, true);
  is(state.unseen, false);
  is(followMarker(state), false);
});

test("scrolling away from the tail pauses following", () => {
  const state = followMoved(followStart, false);
  is(state.following, false);
  is(state.unseen, false, "nothing new has arrived yet, so nothing to announce");
});

test("new output while paused raises the marker", () => {
  const paused = followMoved(followStart, false);
  const state = grew(paused);
  is(state.following, false, "and does not drag the viewport back");
  is(state.unseen, true);
  is(followMarker(state), true);
});

test("more output while the marker is already up changes nothing", () => {
  let state = grew(followMoved(followStart, false));
  const before = state;
  state = grew(state);
  state = grew(state);
  is(state, before, "the marker is a fact, not a counter");
});

test("scrolling back to the tail resumes following and clears the marker", () => {
  let state = grew(followMoved(followStart, false));
  is(followMarker(state), true);
  state = followMoved(state, true);

  is(state.following, true);
  is(state.unseen, false, "arriving at the tail is how a person says keep up");
});

test("returning to the tail deliberately does the same", () => {
  const paused = grew(followMoved(followStart, false));
  const state = followTail();
  is(state.following, true);
  is(state.unseen, false);
  is(followMarker(paused), true, "and the old state is untouched");
});

test("sending a prompt returns to the live tail", () => {
  const paused = grew(followMoved(followStart, false));
  is(followMarker(paused), false || true);
  const state = followSent();
  is(state.following, true);
  is(state.unseen, false);
});

test("a viewport that never left the tail is never marked", () => {
  let state = followStart;
  for (let tick = 0; tick < 50; tick += 1) {
    state = grew(state);
    state = followMoved(state, true);
  }
  is(followMarker(state), false);
  is(state.following, true);
});
