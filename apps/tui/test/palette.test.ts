/**
 * The palette's selection, without a terminal.
 *
 * `Enter runs what is highlighted` is the whole contract, and it was wrong:
 * the first version handled only Escape and Enter, and Enter ran `results[0]`
 * regardless of what a person had moved to. Up and Down did nothing.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { CommandRegistry } from "@comodor/commands";

import { move, open, search, selected, window } from "../src/palette.ts";

interface Ctx { busy?: boolean }

function registry(): CommandRegistry<Ctx> {
  const made = new CommandRegistry<Ctx>();
  made.add(
    { id: "mode.act", title: "Mode: ACT", run: () => {} },
    { id: "mode.plan", title: "Mode: PLAN", run: () => {} },
    { id: "mode.ask", title: "Mode: ASK", run: () => {} },
    { id: "session.new", title: "New session", run: () => {} },
    { id: "session.cancel", title: "Cancel", run: () => {},
      enabled: (context) => Boolean(context.busy) },
    { id: "model.change", title: "Change model", run: () => {} },
    { id: "workspace.open", title: "Open workspace", run: () => {} },
    { id: "settings.open", title: "Open settings", run: () => {} },
    { id: "github.connect", title: "Connect GitHub", run: () => {} },
    { id: "app.quit", title: "Quit", run: () => {} },
  );
  return made;
}

test("opening selects the first result", () => {
  const state = open(registry(), {});
  assert.equal(state.index, 0);
  assert.equal(selected(state)?.id, state.results[0]?.id);
});

test("down and up move the selection", () => {
  let state = open(registry(), {});
  const first = state.results[0]!.id;
  const second = state.results[1]!.id;

  state = move(state, 1);
  assert.equal(selected(state)?.id, second);

  state = move(state, -1);
  assert.equal(selected(state)?.id, first);
});

test("the selection wraps at both ends", () => {
  const state = open(registry(), {});
  const last = state.results[state.results.length - 1]!.id;

  assert.equal(selected(move(state, -1))?.id, last);
  const atEnd = { ...state, index: state.results.length - 1 };
  assert.equal(selected(move(atEnd, 1))?.id, state.results[0]!.id);
});

test("Enter runs what is highlighted, not what happens to be first", () => {
  // The bug this exists for.
  const state = move(move(open(registry(), {}), 1), 1);
  assert.equal(selected(state)?.id, state.results[2]?.id);
  assert.notEqual(selected(state)?.id, state.results[0]?.id);
});

test("changing the query puts the selection back on the first result", () => {
  // An index kept across a rebuilt list highlights whatever is at that
  // position now, which is not what anybody selected.
  const made = registry();
  let state = move(move(open(made, {}), 1), 1);
  assert.equal(state.index, 2);

  state = search(made, {}, "mode");
  assert.equal(state.index, 0);
  assert.ok(selected(state)?.id.startsWith("mode."));
});

test("a query that matches nothing selects nothing and does not crash", () => {
  const state = search(registry(), {}, "zzzzz");

  assert.deepEqual(state.results, []);
  assert.equal(state.index, -1);
  assert.equal(selected(state), undefined);
  // Moving in an empty list is a no-op rather than an index out of range.
  assert.equal(selected(move(state, 1)), undefined);
  assert.equal(move(state, 1).index, -1);
});

test("a disabled command is not offered", () => {
  const shown = open(registry(), { busy: false }).results.map((c) => c.id);
  assert.ok(!shown.includes("session.cancel"));

  const busy = open(registry(), { busy: true }).results.map((c) => c.id);
  assert.ok(busy.includes("session.cancel"));
});

test("the visible window keeps the selection on screen", () => {
  const made = registry();
  let state = open(made, {});
  assert.deepEqual(window(state, 4), { from: 0, to: 4 });

  // Move past the bottom of the window and it scrolls, rather than the
  // selection disappearing off the end of a list that never moves.
  for (let step = 0; step < 6; step += 1) state = move(state, 1);
  const view = window(state, 4);
  assert.ok(state.index >= view.from && state.index < view.to,
    `selection ${state.index} is outside ${JSON.stringify(view)}`);
});

test("a list shorter than the window is not scrolled", () => {
  const state = search(registry(), {}, "mode");
  assert.deepEqual(window(state, 8), { from: 0, to: state.results.length });
});

test("asking for no rows returns an empty window rather than a negative one", () => {
  assert.deepEqual(window(open(registry(), {}), 0), { from: 0, to: 0 });
});
