/**
 * The projection, against the sequences a real core produces — including the
 * ones a buggy core produces, since defining what happens then is the
 * difference between a wrong screen and a screen that says it is wrong.
 */

import { deepStrictEqual as same, ok, strictEqual as is } from "node:assert/strict";
import { test } from "node:test";

import {
  initial,
  reduce,
  streaming,
  timeline,
  toolsOfTurn,
  unsent,
  type Action,
  type Snapshot,
  type State,
} from "../src/index.ts";
import type { Session } from "@comodor/protocol";

const SESSION: Session = {
  id: "s1", mode: "act", workspace: "/w", busy: false,
};

let clock = 0;

/** An event, with the next sequence number, so tests read as sequences. */
function ev(name: string, params: Record<string, unknown>, seq?: number): Action {
  clock = seq ?? clock + 1;
  return { type: "event", name: name as never, params, seq: clock };
}

function run(actions: Action[], from: State = initial): State {
  return actions.reduce(reduce, from);
}

function fresh(): State {
  clock = 0;
  return reduce(initial, { type: "connected", session: SESSION });
}

// --------------------------------------------------------------------------- //
// message correlation
// --------------------------------------------------------------------------- //

test("a delta joins the message its id names, not the newest one", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.started", { turn_id: "t1", message_id: "m2" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "first" }),
    ev("message.delta", { turn_id: "t1", message_id: "m2", text: "second" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "!" }),
  ], fresh());

  same(state.lines.map((line) => [line.id, line.text]),
       [["m1", "first!"], ["m2", "second"]]);
});

test("two messages in one turn are two lines", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "Looking." }),
    ev("message.completed", { turn_id: "t1", message_id: "m1",
                              text: "Looking.", status: "completed" }),
    ev("tool.started", { turn_id: "t1", call_id: "c1", name: "read_file" }),
    ev("tool.completed", { turn_id: "t1", call_id: "c1" }),
    ev("message.started", { turn_id: "t1", message_id: "m2" }),
    ev("message.delta", { turn_id: "t1", message_id: "m2", text: "Done." }),
    ev("message.completed", { turn_id: "t1", message_id: "m2",
                              text: "Done.", status: "completed" }),
  ], fresh());

  is(state.lines.length, 2);
  same(state.lines.map((line) => line.text), ["Looking.", "Done."]);
  ok(state.lines.every((line) => line.turnId === "t1"));
  is(streaming(state), false);
});

test("a delta for an unknown message is dropped, not appended to a neighbour", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "mine" }),
    ev("message.delta", { turn_id: "t1", message_id: "ghost", text: "NOT MINE" }),
  ], fresh());

  is(state.lines.length, 1);
  is(state.lines[0]?.text, "mine");
});

test("a completed event before any start changes nothing", () => {
  const state = run([
    ev("message.completed", { turn_id: "t1", message_id: "m1",
                              text: "hi", status: "completed" }),
  ], fresh());
  is(state.lines.length, 0);
});

test("a second start for the same id restarts it rather than duplicating", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "stale" }),
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "fresh" }),
  ], fresh());

  is(state.lines.length, 1, "two lines with one id is unusable as a key");
  is(state.lines[0]?.text, "fresh");
});

test("the completed text replaces the deltas, so a lost one is corrected", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "Hel" }),
    ev("message.completed", { turn_id: "t1", message_id: "m1",
                              text: "Hello there", status: "completed" }),
  ], fresh());
  is(state.lines[0]?.text, "Hello there");
});

// --------------------------------------------------------------------------- //
// how a message ends
// --------------------------------------------------------------------------- //

test("a cancelled message keeps what arrived and says it was cancelled", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "half an" }),
    ev("message.completed", { turn_id: "t1", message_id: "m1",
                              text: "half an", status: "cancelled" }),
  ], fresh());

  is(state.lines[0]?.state, "cancelled");
  is(state.lines[0]?.text, "half an");
  is(streaming(state), false);
});

test("a failed message carries its reason and stops streaming", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.completed", { turn_id: "t1", message_id: "m1", status: "failed",
                              error: "the provider fell over" }),
  ], fresh());

  is(state.lines[0]?.state, "failed");
  is(state.lines[0]?.error, "the provider fell over");
  is(streaming(state), false);
});

// --------------------------------------------------------------------------- //
// tools
// --------------------------------------------------------------------------- //

test("interleaved output from two tools stays under the right tool", () => {
  const state = run([
    ev("tool.started", { turn_id: "t1", call_id: "a", name: "alpha" }),
    ev("tool.started", { turn_id: "t1", call_id: "b", name: "bravo" }),
    ev("tool.output", { turn_id: "t1", call_id: "a", text: "A1\n" }),
    ev("tool.output", { turn_id: "t1", call_id: "b", text: "B1\n" }),
    ev("tool.output", { turn_id: "t1", call_id: "a", text: "A2\n" }),
    ev("tool.output", { turn_id: "t1", call_id: "b", text: "B2\n" }),
  ], fresh());

  same(state.tools.map((tool) => [tool.id, tool.output]),
       [["a", "A1\nA2\n"], ["b", "B1\nB2\n"]]);
});

test("output for an unknown call is dropped rather than guessed at", () => {
  const state = run([
    ev("tool.started", { turn_id: "t1", call_id: "a", name: "alpha" }),
    ev("tool.output", { turn_id: "t1", call_id: "ghost", text: "not mine" }),
  ], fresh());
  is(state.tools[0]?.output, "");
});

test("a tool reports completed or failed, and carries the reason", () => {
  const state = run([
    ev("tool.started", { turn_id: "t1", call_id: "a", name: "alpha" }),
    ev("tool.started", { turn_id: "t1", call_id: "b", name: "bravo" }),
    ev("tool.completed", { turn_id: "t1", call_id: "a", elapsed_ms: 12 }),
    ev("tool.failed", { turn_id: "t1", call_id: "b", error: "it broke" }),
  ], fresh());

  is(state.tools[0]?.state, "completed");
  is(state.tools[0]?.elapsedMs, 12);
  is(state.tools[1]?.state, "failed");
  is(state.tools[1]?.error, "it broke");
});

test("tools are grouped by the turn that started them", () => {
  const state = run([
    ev("tool.started", { turn_id: "t1", call_id: "a", name: "alpha" }),
    ev("tool.started", { turn_id: "t2", call_id: "b", name: "bravo" }),
  ], fresh());

  same(toolsOfTurn(state, "t1").map((tool) => tool.id), ["a"]);
  same(toolsOfTurn(state, "t2").map((tool) => tool.id), ["b"]);
});

test("a repeated tool.started does not create a second row", () => {
  const state = run([
    ev("tool.started", { turn_id: "t1", call_id: "a", name: "alpha" }),
    ev("tool.output", { turn_id: "t1", call_id: "a", text: "kept" }),
    ev("tool.started", { turn_id: "t1", call_id: "a", name: "alpha" }),
  ], fresh());

  is(state.tools.length, 1);
  is(state.tools[0]?.output, "kept", "and does not wipe what it produced");
});

// --------------------------------------------------------------------------- //
// sending
// --------------------------------------------------------------------------- //

test("a prompt is shown at once and shown as pending", () => {
  const state = reduce(fresh(),
    { type: "sending", localId: "you-1", text: "fix the parser" });

  is(state.lines[0]?.speaker, "you");
  is(state.lines[0]?.text, "fix the parser");
  is(state.lines[0]?.state, "pending");
});

test("a rejected send keeps the text and says why", () => {
  const state = run([
    { type: "sending", localId: "you-1", text: "fix the parser" },
    { type: "rejected", localId: "you-1", reason: "already working" },
  ], fresh());

  is(state.lines[0]?.text, "fix the parser", "the text must not be lost");
  is(state.lines[0]?.state, "failed_to_send");
  is(state.lines[0]?.error, "already working");
  same(unsent(state).map((line) => line.text), ["fix the parser"]);
});

test("a retry clears the failure without duplicating the message", () => {
  const state = run([
    { type: "sending", localId: "you-1", text: "again" },
    { type: "rejected", localId: "you-1", reason: "busy" },
    { type: "retrying", localId: "you-1" },
    { type: "accepted", localId: "you-1", turnId: "t9" },
  ], fresh());

  is(state.lines.length, 1);
  is(state.lines[0]?.state, "completed");
  is(state.lines[0]?.turnId, "t9");
  is(unsent(state).length, 0);
});

// --------------------------------------------------------------------------- //
// sequence, duplicates and gaps
// --------------------------------------------------------------------------- //

test("an event already applied is not applied twice", () => {
  let state = fresh();
  state = reduce(state, ev("message.started", { turn_id: "t1", message_id: "m1" }, 5));
  state = reduce(state, ev("message.delta", { turn_id: "t1", message_id: "m1", text: "x" }, 6));
  // The same delta again, as a redelivery would arrive.
  state = reduce(state, ev("message.delta", { turn_id: "t1", message_id: "m1", text: "x" }, 6));

  is(state.lines[0]?.text, "x");
  is(state.revision, 6);
});

test("an event from before the current revision is dropped", () => {
  let state = fresh();
  state = reduce(state, ev("message.started", { turn_id: "t1", message_id: "m1" }, 10));
  state = reduce(state, ev("message.delta", { turn_id: "t1", message_id: "m1", text: "late" }, 4));

  is(state.lines[0]?.text, "");
  is(state.revision, 10);
});

test("a hole in the sequence is recorded rather than smoothed over", () => {
  let state = fresh();
  state = reduce(state, ev("message.started", { turn_id: "t1", message_id: "m1" }, 3));
  is(state.gap, false);
  state = reduce(state, ev("message.delta", { turn_id: "t1", message_id: "m1", text: "?" }, 9));

  is(state.gap, true, "five events never arrived; the session is incomplete");
  is(state.revision, 9);
});

// --------------------------------------------------------------------------- //
// snapshots
// --------------------------------------------------------------------------- //

function snapshotOf(revision: number): Snapshot {
  return {
    session: { ...SESSION, busy: true },
    revision,
    messages: [
      { message_id: "user-t1", turn_id: "t1", role: "user",
        text: "look at it", status: "completed" },
      { message_id: "m1", turn_id: "t1", role: "assistant",
        text: "Looking.", status: "completed" },
      { message_id: "m2", turn_id: "t1", role: "assistant",
        text: "Still going", status: "streaming" },
    ],
    tools: [
      { call_id: "c1", turn_id: "t1", name: "run_shell", state: "running",
        output: "line one\n" },
    ],
  };
}

test("a snapshot rebuilds the whole visible session", () => {
  const state = reduce(fresh(), { type: "snapshot", snapshot: snapshotOf(20) });

  same(state.lines.map((line) => [line.speaker, line.text, line.state]), [
    ["you", "look at it", "completed"],
    ["comodor", "Looking.", "completed"],
    ["comodor", "Still going", "streaming"],
  ]);
  is(state.tools[0]?.output, "line one\n");
  is(state.tools[0]?.state, "running");
  is(state.revision, 20);
  is(state.connection.kind, "ready");
  is(streaming(state), true);
});

test("events after a snapshot continue it; events before it are dropped", () => {
  let state = reduce(fresh(), { type: "snapshot", snapshot: snapshotOf(20) });
  // An event the snapshot already contains, arriving late.
  state = reduce(state, ev("tool.output", { turn_id: "t1", call_id: "c1",
                                            text: "line one\n" }, 18));
  // And one it does not.
  state = reduce(state, ev("tool.output", { turn_id: "t1", call_id: "c1",
                                            text: "line two\n" }, 21));

  is(state.tools[0]?.output, "line one\nline two\n",
     "the snapshot's own output must not be counted twice");
});

test("a stale snapshot does not undo newer events", () => {
  let state = reduce(fresh(), { type: "snapshot", snapshot: snapshotOf(20) });
  state = reduce(state, ev("tool.output", { turn_id: "t1", call_id: "c1",
                                            text: "line two\n" }, 21));
  // A snapshot built before that event finally arrives.
  state = reduce(state, { type: "snapshot", snapshot: snapshotOf(19) });

  is(state.tools[0]?.output, "line one\nline two\n");
  is(state.revision, 21);
});

test("a snapshot clears a gap, because it is the repair for one", () => {
  let state = fresh();
  state = reduce(state, ev("message.started", { turn_id: "t1", message_id: "m1" }, 3));
  state = reduce(state, ev("message.delta", { turn_id: "t1", message_id: "m1", text: "?" }, 9));
  is(state.gap, true);

  state = reduce(state, { type: "snapshot", snapshot: snapshotOf(30) });
  is(state.gap, false);
});

test("a rebuilt projection equals one that watched the whole thing", () => {
  // A: connected throughout.
  clock = 0;
  const timeline: Action[] = [
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "Looking." }),
    ev("message.completed", { turn_id: "t1", message_id: "m1",
                              text: "Looking.", status: "completed" }),
    ev("tool.started", { turn_id: "t1", call_id: "c1", name: "run_shell" }),
    ev("tool.output", { turn_id: "t1", call_id: "c1", text: "one\n" }),
    ev("tool.output", { turn_id: "t1", call_id: "c1", text: "two\n" }),
    ev("tool.completed", { turn_id: "t1", call_id: "c1" }),
  ];
  const watched = run(timeline, fresh());

  // B: joined at the fifth event, from a snapshot describing the first four.
  const halfway = run(timeline.slice(0, 5), fresh());
  const rebuilt = run(timeline.slice(5), reduce(fresh(), {
    type: "snapshot",
    snapshot: {
      session: SESSION,
      revision: 5,
      messages: [{ message_id: "m1", turn_id: "t1", role: "assistant",
                   text: "Looking.", status: "completed" }],
      tools: [{ call_id: "c1", turn_id: "t1", name: "run_shell",
                state: "running", output: "one\n" }],
    },
  }));

  is(halfway.tools[0]?.output, "one\n");
  same(rebuilt.lines.map((line) => [line.id, line.text, line.state]),
       watched.lines.map((line) => [line.id, line.text, line.state]));
  same(rebuilt.tools.map((tool) => [tool.id, tool.output, tool.state]),
       watched.tools.map((tool) => [tool.id, tool.output, tool.state]));
});

test("a snapshot that shortened output says so", () => {
  const state = reduce(fresh(), {
    type: "snapshot",
    snapshot: {
      session: SESSION, revision: 4, messages: [],
      tools: [{ call_id: "c1", turn_id: "t1", name: "run_shell",
                state: "completed", output: "…the tail", output_truncated: true }],
    },
  });
  is(state.tools[0]?.outputTruncated, true);
});

// --------------------------------------------------------------------------- //
// connection and mode
// --------------------------------------------------------------------------- //

test("resynchronising is not the same state as starting", () => {
  const state = reduce(fresh(), { type: "resynchronising" });
  is(state.connection.kind, "resynchronising");
});

test("the mode follows the core and nothing else", () => {
  const state = run([
    ev("mode.changed", { session_id: "s1", mode: "plan" }),
  ], fresh());
  is(state.session?.mode, "plan");
});

test("an unknown event leaves the state alone", () => {
  const before = fresh();
  const after = reduce(before, ev("something.new" as never, { any: 1 }));
  same(after.lines, before.lines);
  same(after.tools, before.tools);
});

// --------------------------------------------------------------------------- //
// drawing order
// --------------------------------------------------------------------------- //

test("the timeline interleaves messages and the tools between them", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "Looking." }),
    ev("message.completed", { turn_id: "t1", message_id: "m1",
                              text: "Looking.", status: "completed" }),
    ev("tool.started", { turn_id: "t1", call_id: "c1", name: "read_file" }),
    ev("tool.started", { turn_id: "t1", call_id: "c2", name: "run_shell" }),
    ev("tool.completed", { turn_id: "t1", call_id: "c1" }),
    ev("message.started", { turn_id: "t1", message_id: "m2" }),
    ev("message.delta", { turn_id: "t1", message_id: "m2", text: "Done." }),
  ], fresh());

  same(timeline(state).map((entry) => entry.kind === "line"
    ? `msg:${entry.line.text}` : `tool:${entry.tool.name}`),
    ["msg:Looking.", "tool:read_file", "tool:run_shell", "msg:Done."]);
});

test("the person's prompt comes before the answer to it", () => {
  let state = fresh();
  state = reduce(state, { type: "sending", localId: "you-1", text: "hello" });
  state = reduce(state, { type: "accepted", localId: "you-1", turnId: "t1" });
  state = reduce(state, ev("message.started", { turn_id: "t1", message_id: "m1" }));
  state = reduce(state, ev("message.delta", { turn_id: "t1", message_id: "m1",
                                              text: "hi back" }));

  same(timeline(state).map((entry) => entry.kind === "line"
    ? entry.line.text : "?"), ["hello", "hi back"]);
});

test("a snapshot's timeline keeps a turn's messages and tools together", () => {
  const state = reduce(fresh(), { type: "snapshot", snapshot: snapshotOf(9) });
  const order = timeline(state).map((entry) => entry.kind);
  is(order.filter((kind) => kind === "line").length, 3);
  is(order.filter((kind) => kind === "tool").length, 1);
  // Ordering is total and stable, which is what a keyed render needs.
  const at = timeline(state).map((entry) => entry.at);
  same(at, [...at].sort((left, right) => left - right));
  is(new Set(at).size, at.length, "two entries must never share a position");
});
