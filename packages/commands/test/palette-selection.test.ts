/**
 * The palette's selection rule, shared by every client (D2, research R8):
 * the highlight goes back to the first result whenever the query changes,
 * is -1 when there is no result, and moves within the results.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  CommandRegistry, moveSelection, selectedCommand, selectionFor, type Command,
} from "../src/index.ts";

interface Context { busy: boolean }

function registry(): CommandRegistry<Context> {
  const command = (id: string, title: string, extra: Partial<Command<Context>> = {}):
      Command<Context> => ({ id, title, run: () => {}, ...extra });
  return new CommandRegistry<Context>().add(
    command("view.core", "Show the Core panel"),
    command("view.diagnostics", "Show diagnostics"),
    command("layout.reset", "Reset layout"),
    command("conversation.cancel", "Cancel", { enabled: (context) => context.busy }),
  );
}

test("the selection starts on the first result", () => {
  const state = selectionFor(registry(), { busy: false }, "");
  assert.equal(state.query, "");
  assert.equal(state.index, 0);
  assert.deepEqual(state.results.map((command) => command.id),
                   ["view.core", "view.diagnostics", "layout.reset"]);
});

test("every change of the query puts the highlight back on the first result", () => {
  const commands = registry();
  const idle: Context = { busy: false };
  let state = selectionFor(commands, idle, "show");
  state = moveSelection(state, 1);
  assert.equal(state.index, 1);
  state = selectionFor(commands, idle, "sho");
  assert.equal(state.index, 0, "back to the first result");
  assert.equal(selectedCommand(state)?.id, state.results[0]?.id);
});

test("no result means no highlight", () => {
  const state = selectionFor(registry(), { busy: false }, "terminal");
  assert.equal(state.results.length, 0);
  assert.equal(state.index, -1);
  assert.equal(selectedCommand(state), undefined);
  assert.equal(moveSelection(state, 1), state);
});

test("moving wraps within the results", () => {
  const state = selectionFor(registry(), { busy: false }, "");
  assert.equal(moveSelection(state, -1).index, 2);
  assert.equal(moveSelection(moveSelection(state, 2), 1).index, 0);
});

test("only enabled commands are results", () => {
  assert.ok(!selectionFor(registry(), { busy: false }, "cancel").results
    .some((command) => command.id === "conversation.cancel"));
  assert.ok(selectionFor(registry(), { busy: true }, "cancel").results
    .some((command) => command.id === "conversation.cancel"));
});
